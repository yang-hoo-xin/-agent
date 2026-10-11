// Observe the actual compiled SpreadAPI, instrumenting only its game callback.
// 为什么要有它：公开 API 的数值与副作用计数可以独立复验，但跳过游戏回调不能证明游戏运行时行为。
using System.Globalization;
using System.Reflection;
using System.Runtime.Loader;
using System.Security.Cryptography;
using System.Text.Json;

static string Hash(string path) => Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(path))).ToLowerInvariant();
static string Verify(JsonElement reference)
{
    string path = Path.GetFullPath(reference.GetProperty("path").GetString()!);
    if (Hash(path) != reference.GetProperty("sha256").GetString())
        throw new InvalidDataException("SPREAD_PROBE_FILE_HASH_CHANGED");
    return path;
}
static Exception Unwrap(Exception error)
{
    while ((error is TargetInvocationException || error is TypeInitializationException) && error.InnerException != null)
        error = error.InnerException;
    return error;
}
static float Number(string value) => value switch {
    "NaN" => float.NaN, "Infinity" => float.PositiveInfinity,
    "-Infinity" => float.NegativeInfinity,
    _ => float.Parse(value, CultureInfo.InvariantCulture)
};

string phase = "probe_setup";
const string scope = "cold_compiled_spread_api_real_harmony_callback_count_game_callback_body_skipped_not_game_runtime";
try
{
    // 为什么要有它：当前绑定 Harmony 在 .NET 7 会漏掉 API 内部调用；仅允许已实测计数正确的 .NET 6 运行时。
    if (Environment.Version.Major != 6)
        throw new InvalidDataException("SPREAD_PROBE_NET6_RUNTIME_REQUIRED");
    using var input = JsonDocument.Parse(File.ReadAllBytes(args.Single()));
    var request = input.RootElement;
    string assemblyPath = Verify(request.GetProperty("assembly"));
    string sandbox = Path.GetFullPath(request.GetProperty("sandbox_root").GetString()!);
    if (!Directory.Exists(sandbox) || Directory.EnumerateFileSystemEntries(sandbox).Any())
        throw new InvalidDataException("SPREAD_PROBE_EMPTY_SANDBOX_REQUIRED");
    var dependencies = new Dictionary<string, string>(StringComparer.Ordinal);
    foreach (var reference in request.GetProperty("dependencies").EnumerateArray())
    {
        string path = Verify(reference);
        try
        {
            string name = AssemblyName.GetAssemblyName(path).Name!;
            if (dependencies.TryGetValue(name, out var prior) && Hash(prior) != Hash(path))
                throw new InvalidDataException("SPREAD_PROBE_AMBIGUOUS_ASSEMBLY");
            dependencies[name] = path;
        }
        catch (BadImageFormatException) { }
    }
    AssemblyLoadContext.Default.Resolving += (context, name) =>
        name.Name != null && dependencies.TryGetValue(name.Name, out var path)
            ? context.LoadFromAssemblyPath(path) : null;
    var core = AssemblyLoadContext.Default.LoadFromAssemblyPath(dependencies["BepInEx.Core"]);
    var paths = core.GetType("BepInEx.Paths", true)!;
    paths.GetMethod("SetExecutablePath", BindingFlags.Public | BindingFlags.Static,
        new[] { typeof(string), typeof(string), typeof(string), typeof(bool), typeof(string[]) })!
        .Invoke(null, new object?[] { Path.Combine(sandbox, "SpreadProbe.exe"),
            Path.Combine(sandbox, "BepInEx"), null, false, Array.Empty<string>() });
    string configPath = (string)paths.GetProperty("ConfigPath")!.GetValue(null)!;
    if (!Path.GetFullPath(configPath).StartsWith(sandbox + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase))
        throw new InvalidDataException("SPREAD_PROBE_CONFIG_PATH_ESCAPED");
    Directory.CreateDirectory(configPath);
    var mod = AssemblyLoadContext.Default.LoadFromAssemblyPath(assemblyPath);
    // 为什么要有它：产品 API 缺失或签名漂移属于候选契约失败，不能误记成探针或 Harmony 的基础设施故障。
    phase = "api_contract";
    var api = mod.GetType("AccurateCrosshair.API.SpreadAPI", false)
        ?? throw new TypeLoadException("SPREAD_PROBE_PUBLIC_API_TYPE_REQUIRED");
    if (!api.IsPublic || api.ContainsGenericParameters)
        throw new InvalidDataException("SPREAD_PROBE_PUBLIC_API_TYPE_REQUIRED");
    MethodInfo RequireMethod(string name, params Type[] parameters) =>
        api.GetMethods(BindingFlags.Public | BindingFlags.Static | BindingFlags.FlattenHierarchy)
            .SingleOrDefault(method => method.Name == name && method.ReturnType == typeof(void)
                && !method.ContainsGenericParameters
                && method.GetParameters().Select(parameter => parameter.ParameterType).SequenceEqual(parameters))
        ?? throw new MissingMethodException("SPREAD_PROBE_PUBLIC_STATIC_VOID_" + name + "_SIGNATURE_REQUIRED");
    var set = RequireMethod("SetModifier", typeof(object), typeof(float));
    var remove = RequireMethod("RemoveModifier", typeof(object));
    var valueProperty = api.GetProperties(BindingFlags.Public | BindingFlags.Static | BindingFlags.FlattenHierarchy)
        .SingleOrDefault(property => property.Name == "SpreadModifier" && property.PropertyType == typeof(float)
            && property.GetIndexParameters().Length == 0
            && property.GetMethod is { IsPublic: true, IsStatic: true, ContainsGenericParameters: false })
        ?? throw new MissingMemberException("SPREAD_PROBE_PUBLIC_STATIC_FLOAT_SpreadModifier_GETTER_REQUIRED");
    phase = "callback_instrumentation";
    var callback = mod.GetType("AccurateCrosshair.CrosshairPatches.SpreadPatches", true)!
        .GetMethod("UpdateCrosshairSize", BindingFlags.Public | BindingFlags.Static, Type.EmptyTypes)!;
    var harmonyAssembly = AssemblyLoadContext.Default.LoadFromAssemblyPath(dependencies["0Harmony"]);
    var harmonyType = harmonyAssembly.GetType("HarmonyLib.Harmony", true)!;
    var methodType = harmonyAssembly.GetType("HarmonyLib.HarmonyMethod", true)!;
    var harmony = Activator.CreateInstance(harmonyType, "codex.cold.spread.probe")!;
    var prefix = Activator.CreateInstance(methodType,
        new object[] { typeof(CallbackCounter).GetMethod(nameof(CallbackCounter.Prefix))! })!;
    var patch = harmonyType.GetMethods().Single(m => m.Name == "Patch" && m.GetParameters().Length == 5);
    patch.Invoke(harmony, new object?[] { callback, prefix, null, null, null });
    // 为什么要有它：先直接调用被拦截方法确认计数链路有效，再归零；否则零回调可能来自失效的观测器。
    phase = "callback_calibration";
    callback.Invoke(null, null);
    if (CallbackCounter.Count != 1) throw new InvalidOperationException("SPREAD_PROBE_CALLBACK_CALIBRATION_FAILED");
    CallbackCounter.Count = 0;
    string ReadValue() => ((float)valueProperty.GetValue(null)!).ToString("R", CultureInfo.InvariantCulture);
    var observations = new List<object>();
    var keys = new Dictionary<string, object>(StringComparer.Ordinal);
    phase = "api_sequence";
    string initialValue = ReadValue();
    foreach (var action in request.GetProperty("actions").EnumerateArray())
    {
        string id = action.GetProperty("id").GetString()!;
        string operation = action.GetProperty("operation").GetString()!;
        string key = action.GetProperty("key").GetString()!;
        if (!keys.TryGetValue(key, out var keyObject)) keys[key] = keyObject = new object();
        string before = ReadValue();
        int callbacksBefore = CallbackCounter.Count;
        Exception? failure = null;
        if (operation != "set" && operation != "remove") throw new InvalidDataException("SPREAD_PROBE_UNKNOWN_ACTION");
        float? argument = operation == "set" ? Number(action.GetProperty("value").GetString()!) : null;
        try
        {
            if (operation == "set") set.Invoke(null, new object[] { keyObject, argument!.Value });
            else remove.Invoke(null, new[] { keyObject });
        }
        catch (Exception error) { failure = Unwrap(error); }
        observations.Add(new { id, operation, key, argument = argument?.ToString("R", CultureInfo.InvariantCulture),
            value_before = before, value = ReadValue(), callbacks_before = callbacksBefore,
            callback_count = CallbackCounter.Count, callback_delta = CallbackCounter.Count - callbacksBefore,
            exception_type = failure?.GetType().FullName, exception_message = failure?.Message });
    }
    Console.WriteLine(JsonSerializer.Serialize(new { status = "observed", process_id = Environment.ProcessId,
        protocol = "spread-api-probe.v1", initial_value = initialValue, observations,
        mode = "real_harmony_callback_prefix", runtime_version = Environment.Version.ToString(),
        assembly_sha256 = Hash(assemblyPath), callback_calibration_count = 1,
        callback_method = callback.DeclaringType!.FullName + "." + callback.Name,
        callback_body_skipped = true, api_methods_instrumented = false,
        configuration_path = configPath,
        loaded_dependencies = AppDomain.CurrentDomain.GetAssemblies().Where(a => !a.IsDynamic &&
            (dependencies.ContainsKey(a.GetName().Name!) ||
             a.GetName().Name is "System.Private.CoreLib" or "System.Runtime" or "netstandard")).Select(a => new {
                name = a.GetName().Name, path = a.Location, sha256 = Hash(a.Location) }).ToArray(), scope }));
    return 0;
}
catch (Exception error)
{
    error = Unwrap(error);
    Console.WriteLine(JsonSerializer.Serialize(new { status = "execution_failed", execution_phase = phase,
        error_type = error.GetType().FullName, message = error.Message,
        stack_trace = error.StackTrace, process_id = Environment.ProcessId, scope }));
    return 2;
}

public static class CallbackCounter
{
    public static int Count;
    public static bool Prefix() { Count++; return false; }
}
