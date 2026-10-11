// Observe complete compiled CLI executions and actual disk bytes.
// 为什么要有它：独立 CLI 进程与磁盘前后像能证明持久化行为，但环境白名单不等于操作系统安全沙箱。
using System.Diagnostics;
using System.Reflection;
using System.Runtime.Loader;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

static string Hash(string path) => Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(path))).ToLowerInvariant();
static string Verify(JsonElement reference)
{
    string path = Path.GetFullPath(reference.GetProperty("path").GetString()!);
    if (Hash(path) != reference.GetProperty("sha256").GetString())
        throw new InvalidDataException("CONFIG_CLI_PROBE_FILE_HASH_CHANGED: " + path);
    return path;
}
static object FileState(string path) => File.Exists(path)
    ? new { exists = true, text = (string?)Encoding.UTF8.GetString(File.ReadAllBytes(path)), sha256 = (string?)Hash(path) }
    : new { exists = false, text = (string?)null, sha256 = (string?)null };
static object[] Files(string sandbox) => Directory.EnumerateFiles(sandbox, "*", SearchOption.AllDirectories)
    .OrderBy(path => path, StringComparer.Ordinal)
    .Select(path => (object)new { path = Path.GetRelativePath(sandbox, path).Replace('\\', '/'), sha256 = Hash(path) }).ToArray();

string phase = "probe_setup";
const string scope = "real_compiled_cli_independent_processes_fixed_runtime_disk_observation_not_os_sandbox_not_game_runtime";
try
{
    if (Environment.Version.Major != 7)
        throw new InvalidDataException("CONFIG_CLI_PROBE_NET7_RUNTIME_REQUIRED");
    using var document = JsonDocument.Parse(File.ReadAllBytes(args.Single()));
    var request = document.RootElement;
    string assemblyPath = Verify(request.GetProperty("assembly"));
    var assemblyReferences = request.GetProperty("assembly_files").EnumerateArray().ToArray();
    var boundPaths = assemblyReferences.Select(Verify).ToHashSet(StringComparer.OrdinalIgnoreCase);
    string prefix = Path.Combine(Path.GetDirectoryName(assemblyPath)!, Path.GetFileNameWithoutExtension(assemblyPath));
    if (!new[] { assemblyPath, prefix + ".deps.json", prefix + ".runtimeconfig.json" }.All(boundPaths.Contains))
        throw new InvalidDataException("CONFIG_CLI_PROBE_ASSEMBLY_SIDECARS_REQUIRED");
    foreach (var reference in request.GetProperty("dependencies").EnumerateArray()) Verify(reference);
    string dotnet = request.TryGetProperty("dotnet_ref", out var dotnetReference)
        ? Verify(dotnetReference) : Environment.ProcessPath!;
    if (!Path.GetFileNameWithoutExtension(dotnet).Equals("dotnet", StringComparison.OrdinalIgnoreCase))
        throw new InvalidDataException("CONFIG_CLI_PROBE_DOTNET_HOST_REQUIRED");
    string sandbox = Path.GetFullPath(request.GetProperty("sandbox_root").GetString()!);
    if (!Directory.Exists(sandbox) || Directory.EnumerateFileSystemEntries(sandbox).Any())
        throw new InvalidDataException("CONFIG_CLI_PROBE_EMPTY_SANDBOX_REQUIRED");
    string config = Path.Combine(sandbox, "config", "nested", "settings.json");
    if (request.TryGetProperty("seed_file", out var seed) && seed.ValueKind != JsonValueKind.Null)
    {
        Directory.CreateDirectory(Path.GetDirectoryName(config)!);
        File.WriteAllText(config, seed.GetString(), new UTF8Encoding(false));
    }
    object initialFile = FileState(config);
    // 为什么要有它：旧项目缺少新增 API 是产品反例，不能阻止收集它现有 CLI 的真实行为。
    bool apiContractPresent = false;
    string? apiContractError = null;
    Type? storeType = null;
    MethodInfo? mergeMethod = null;
    try
    {
        var assembly = AssemblyLoadContext.Default.LoadFromAssemblyPath(assemblyPath);
        storeType = assembly.GetType("OwnedConfigService.JsonConfigStore", false);
        mergeMethod = storeType is { IsPublic: true } ? storeType.GetMethods(BindingFlags.Public | BindingFlags.Instance)
            .SingleOrDefault(method => method.DeclaringType == storeType && method.Name == "Merge" && !method.IsGenericMethod
                && method.ReturnType == typeof(void) && method.GetParameters().Select(p => p.ParameterType)
                    .SequenceEqual(new[] { typeof(JsonElement) })) : null;
        apiContractPresent = mergeMethod != null;
    }
    catch (Exception error) { apiContractError = error.GetType().FullName + ": " + error.Message; }

    phase = "cli_sequence";
    string mode = request.TryGetProperty("mode", out var modeElement) ? modeElement.GetString()! : "cli";
    if (mode is not ("cli" or "api_merge")) throw new InvalidDataException("CONFIG_CLI_PROBE_UNKNOWN_MODE");
    if (mode == "api_merge" && request.GetProperty("actions").GetArrayLength() != 1)
        throw new InvalidDataException("CONFIG_CLI_PROBE_API_SINGLE_ACTION_REQUIRED");
    var observations = new List<object>();
    var environmentKeys = new SortedSet<string>(StringComparer.Ordinal);
    foreach (var action in request.GetProperty("actions").EnumerateArray())
    {
        foreach (var reference in assemblyReferences) Verify(reference);
        string id = action.GetProperty("id").GetString()!;
        var actionArgs = action.GetProperty("args").EnumerateArray().Select(value => value.GetString()!).ToArray();
        // 为什么要有它：固定配置路径限制探针自身授权的写入目标，避免测试输入把 CLI 指向工作区外文件。
        if (actionArgs.Length < 2 || actionArgs[1] != "$CONFIG")
            throw new InvalidDataException("CONFIG_CLI_PROBE_CONFIG_PLACEHOLDER_REQUIRED");
        var expanded = (string[])actionArgs.Clone();
        expanded[1] = config;
        var before = FileState(config);
        if (mode == "api_merge")
        {
            // 为什么要有它：公开 API 必须直接拒绝非法根值，CLI 预检不能代替 API 自身的契约。
            phase = "api_sequence";
            if (actionArgs.Length != 3 || actionArgs[0] != "merge")
                throw new InvalidDataException("CONFIG_CLI_PROBE_API_ACTION_INVALID");
            Exception? failure = null;
            try
            {
                if (mergeMethod == null) throw new MissingMethodException("public void JsonConfigStore.Merge(JsonElement)");
                using var value = JsonDocument.Parse(actionArgs[2]);
                var store = Activator.CreateInstance(storeType!, config);
                mergeMethod.Invoke(store, new object[] { value.RootElement });
            }
            catch (Exception error)
            {
                while (error is TargetInvocationException && error.InnerException != null) error = error.InnerException;
                failure = error;
            }
            var baseTypes = new List<string>();
            for (Type? type = failure?.GetType().BaseType; type != null; type = type.BaseType)
                baseTypes.Add(type.FullName!);
            foreach (var reference in assemblyReferences) Verify(reference);
            observations.Add(new { id, args = actionArgs, expanded_args = expanded, mode,
                process_id = Environment.ProcessId, before_file = before, after_file = FileState(config),
                exception_type = failure?.GetType().FullName, exception_base_types = baseTypes,
                exception_message = failure?.Message, return_value = (object?)null, sandbox_files = Files(sandbox) });
            continue;
        }
        var start = new ProcessStartInfo(dotnet) { WorkingDirectory = sandbox, UseShellExecute = false,
            RedirectStandardOutput = true, RedirectStandardError = true, CreateNoWindow = true,
            StandardOutputEncoding = Encoding.UTF8, StandardErrorEncoding = Encoding.UTF8 };
        // 为什么要有它：子 CLI 必须使用探针已绑定的同一运行时，避免目标配置自动滚动到未绑定版本。
        foreach (string argument in new[] { "exec", "--fx-version", Environment.Version.ToString(), "--roll-forward", "Disable", assemblyPath })
            start.ArgumentList.Add(argument);
        foreach (string argument in expanded) start.ArgumentList.Add(argument);
        var inherited = new[] { "SystemRoot", "WINDIR", "SystemDrive", "COMSPEC", "PATH", "PATHEXT",
            "PROCESSOR_ARCHITECTURE", "NUMBER_OF_PROCESSORS", "DOTNET_ROOT", "DOTNET_ROOT_X64" }
            .Select(key => (key, value: Environment.GetEnvironmentVariable(key))).ToArray();
        start.Environment.Clear();
        foreach (var item in inherited) if (item.value != null) start.Environment[item.key] = item.value;
        foreach (string key in new[] { "TEMP", "TMP", "HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "DOTNET_CLI_HOME" })
            start.Environment[key] = sandbox;
        start.Environment["DOTNET_SKIP_FIRST_TIME_EXPERIENCE"] = "1";
        start.Environment["DOTNET_CLI_TELEMETRY_OPTOUT"] = "1";
        start.Environment["DOTNET_NOLOGO"] = "1";
        foreach (string key in start.Environment.Keys) environmentKeys.Add(key);
        using var process = Process.Start(start) ?? throw new IOException("CONFIG_CLI_PROBE_PROCESS_START_FAILED");
        int pid = process.Id;
        var stdoutTask = process.StandardOutput.ReadToEndAsync();
        var stderrTask = process.StandardError.ReadToEndAsync();
        bool timedOut = !process.WaitForExit(20000);
        if (timedOut) { process.Kill(entireProcessTree: true); process.WaitForExit(5000); }
        string stdout = await stdoutTask;
        string stderr = await stderrTask;
        foreach (var reference in assemblyReferences) Verify(reference);
        observations.Add(new { id, args = actionArgs, expanded_args = expanded, process_id = pid, mode, exit_code = process.ExitCode,
            host_command = dotnet, host_arguments = start.ArgumentList.ToArray(), fixed_runtime_version = Environment.Version.ToString(),
            timed_out = timedOut, stdout, stderr, before_file = before, after_file = FileState(config), sandbox_files = Files(sandbox) });
        if (timedOut) break;
    }
    Verify(request.GetProperty("assembly"));
    foreach (var reference in assemblyReferences) Verify(reference);
    Console.WriteLine(JsonSerializer.Serialize(new { status = "observed", protocol = "config-cli-probe.v1",
        assembly_sha256 = Hash(assemblyPath), assembly_files = assemblyReferences, api_methods_instrumented = false,
        api_contract_present = apiContractPresent, api_contract_error = apiContractError, observations, mode,
        initial_file = initialFile, final_file = FileState(config), sandbox_files = Files(sandbox),
        runtime_version = Environment.Version.ToString(), process_id = Environment.ProcessId,
        environment_keys = environmentKeys, configuration_path = config,
        loaded_dependencies = AppDomain.CurrentDomain.GetAssemblies().Where(a => !a.IsDynamic &&
            !string.IsNullOrEmpty(a.Location) && !a.Location.Equals(assemblyPath, StringComparison.OrdinalIgnoreCase))
            .Select(a => new { name = a.GetName().Name, path = a.Location, sha256 = Hash(a.Location) }).ToArray(), scope }));
    return 0;
}
catch (Exception error)
{
    Console.WriteLine(JsonSerializer.Serialize(new { status = "execution_failed", execution_phase = phase,
        error_type = error.GetType().FullName, message = error.Message, stack_trace = error.StackTrace,
        process_id = Environment.ProcessId, scope }));
    return 2;
}
