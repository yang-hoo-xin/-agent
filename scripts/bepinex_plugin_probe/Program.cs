// Cold-call the bound compiled BasePlugin.Load with real BepInEx config and logging.
// 为什么要有它：隔离构造器与游戏启动允许观测配置/日志逻辑，但不能据此声称游戏运行时通过。
using System.Collections;
using System.Reflection;
using System.Runtime.Loader;
using System.Runtime.Serialization;
using System.Security.Cryptography;
using System.Text.Json;

static string Hash(string path) => Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(path))).ToLowerInvariant();
static string Verify(JsonElement reference)
{
    string path = Path.GetFullPath(reference.GetProperty("path").GetString()!);
    if (Hash(path) != reference.GetProperty("sha256").GetString())
        throw new InvalidDataException("PLUGIN_PROBE_FILE_HASH_CHANGED");
    return path;
}
static object? Property(Type type, object? target, string name) =>
    (type.GetProperty(name, BindingFlags.Static | BindingFlags.Instance | BindingFlags.Public)
     ?? throw new MissingMemberException(type.FullName, name)).GetValue(target);
static void Inject(Type owner, object target, string name, object value)
{
    var field = owner.GetField("<" + name + ">k__BackingField", BindingFlags.NonPublic | BindingFlags.Instance)
        ?? throw new MissingFieldException(owner.FullName, name);
    field.SetValue(target, value);
    if (!ReferenceEquals(Property(owner, target, name), value))
        throw new InvalidOperationException("PLUGIN_PROBE_BASE_PROPERTY_INJECTION_FAILED");
}

string phase = "probe_setup";
string? pluginTypeName = null;
try
{
    using var input = JsonDocument.Parse(File.ReadAllBytes(args.Single()));
    var request = input.RootElement;
    string assemblyPath = Verify(request.GetProperty("assembly"));
    string sandbox = Path.GetFullPath(request.GetProperty("sandbox_root").GetString()!);
    if (!Directory.Exists(sandbox) || Directory.EnumerateFileSystemEntries(sandbox).Any())
        throw new InvalidDataException("PLUGIN_PROBE_EMPTY_SANDBOX_REQUIRED");
    var dependencies = new Dictionary<string, string>(StringComparer.Ordinal);
    foreach (var reference in request.GetProperty("dependencies").EnumerateArray())
    {
        string path = Verify(reference);
        try
        {
            string name = AssemblyName.GetAssemblyName(path).Name!;
            if (dependencies.TryGetValue(name, out var prior) && Hash(prior) != Hash(path))
                throw new InvalidDataException("PLUGIN_PROBE_AMBIGUOUS_ASSEMBLY");
            dependencies[name] = path;
        }
        catch (BadImageFormatException) { }
    }
    AssemblyLoadContext.Default.Resolving += (context, name) =>
        name.Name != null && dependencies.TryGetValue(name.Name, out var path)
            ? context.LoadFromAssemblyPath(path) : null;
    var core = AssemblyLoadContext.Default.LoadFromAssemblyPath(dependencies["BepInEx.Core"]);
    var runtime = AssemblyLoadContext.Default.LoadFromAssemblyPath(dependencies["BepInEx.Unity.IL2CPP"]);
    var paths = core.GetType("BepInEx.Paths", true)!;
    paths.GetMethod("SetExecutablePath", BindingFlags.Public | BindingFlags.Static,
        new[] { typeof(string), typeof(string), typeof(string), typeof(bool), typeof(string[]) })!
        .Invoke(null, new object?[] { Path.Combine(sandbox, "PluginProbe.exe"),
            Path.Combine(sandbox, "BepInEx"), null, false, Array.Empty<string>() });
    string configDirectory = (string)Property(paths, null, "ConfigPath")!;
    string configPath = Path.Combine(configDirectory, "cold-plugin.cfg");
    if (!Path.GetFullPath(configPath).StartsWith(sandbox + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase))
        throw new InvalidDataException("PLUGIN_PROBE_CONFIG_PATH_ESCAPED");
    Directory.CreateDirectory(configDirectory);
    if (request.TryGetProperty("seed_config", out var seed) && seed.ValueKind == JsonValueKind.String)
        File.WriteAllText(configPath, seed.GetString());
    var mod = AssemblyLoadContext.Default.LoadFromAssemblyPath(assemblyPath);
    var basePlugin = runtime.GetType("BepInEx.Unity.IL2CPP.BasePlugin", true)!;
    var pluginType = request.TryGetProperty("type_name", out var typeName)
        ? mod.GetType(typeName.GetString()!, true)!
        : mod.GetTypes().Single(t => basePlugin.IsAssignableFrom(t) && !t.IsAbstract);
    pluginTypeName = pluginType.FullName;
    if (!basePlugin.IsAssignableFrom(pluginType) || pluginType.IsAbstract)
        throw new InvalidDataException("PLUGIN_PROBE_BASE_PLUGIN_REQUIRED");
    var configType = core.GetType("BepInEx.Configuration.ConfigFile", true)!;
    var metadataType = core.GetType("BepInEx.BepInPlugin", true)!;
    var metadata = pluginType.GetCustomAttributes(metadataType, false).SingleOrDefault();
    var config = Activator.CreateInstance(configType, new object?[] { configPath, true, metadata })!;
    var logType = core.GetType("BepInEx.Logging.ManualLogSource", true)!;
    var logger = Activator.CreateInstance(logType, "ColdPluginProbe")!;
    var logs = new List<object>();
    var globalLogger = core.GetType("BepInEx.Logging.Logger", true)!;
    var listenerType = core.GetType("BepInEx.Logging.ILogListener", true)!;
    var listener = typeof(DispatchProxy).GetMethod("Create", Type.EmptyTypes)!
        .MakeGenericMethod(listenerType, typeof(ProbeLogListener)).Invoke(null, null)!;
    ((ProbeLogListener)listener).Capture = (sender, value) => logs.Add(new {
        level = Property(value.GetType(), value, "Level")?.ToString(),
        message = Property(value.GetType(), value, "Data")?.ToString(),
        source = Property(sender.GetType(), sender, "SourceName")?.ToString() });
    var listeners = Property(globalLogger, null, "Listeners")!;
    // 为什么要有它：BepInEx 显式 ICollection.Add 才会更新过滤器与事件订阅，直接反射 HashSet.Add 会静默漏日志。
    typeof(ICollection<>).MakeGenericType(listenerType).GetMethod("Add")!.Invoke(listeners, new[] { listener });
    var sources = Property(globalLogger, null, "Sources")!;
    typeof(ICollection<>).MakeGenericType(core.GetType("BepInEx.Logging.ILogSource", true)!)
        .GetMethod("Add")!.Invoke(sources, new[] { logger });
    phase = "plugin_allocation";
    // 为什么要有它：不运行 BasePlugin/插件实例构造器，避免链式加载器初始化；记录此边界以免混同正常生命周期。
    var plugin = FormatterServices.GetUninitializedObject(pluginType);
    Inject(basePlugin, plugin, "Config", config);
    Inject(basePlugin, plugin, "Log", logger);
    phase = "plugin_load";
    var load = pluginType.GetMethod("Load", BindingFlags.Instance | BindingFlags.Public,
        Type.EmptyTypes) ?? throw new MissingMethodException(pluginType.FullName, "Load");
    load.Invoke(plugin, null);
    phase = "probe_observation";
    var indexer = configType.GetProperty("Item", new[] { typeof(string), typeof(string) })!;
    object[] ReadEntries() => ((IEnumerable)Property(configType, config, "Keys")!).Cast<object>().Select(key => {
        string section = (string)Property(key.GetType(), key, "Section")!;
        string label = (string)Property(key.GetType(), key, "Key")!;
        var entry = indexer.GetValue(config, new object[] { section, label })!;
        var settingType = (Type)Property(entry.GetType(), entry, "SettingType")!;
        return (object)new { section, key = label, value = Property(entry.GetType(), entry, "BoxedValue"),
            default_value = Property(entry.GetType(), entry, "DefaultValue"), value_type = settingType.FullName };
    }).ToArray();
    var entries = ReadEntries();
    var initialLogs = logs.ToArray();
    configType.GetMethod("Save", Type.EmptyTypes)!.Invoke(config, null);
    string initialSavedConfig = File.ReadAllText(configPath);
    var reloadObservations = new List<object>();
    int reloadCalls = 0, reloadNotifications = 0;
    if (request.TryGetProperty("reload_actions", out var reloadActions))
    {
        // 为什么要有它：动作只写已验证sandbox配置文件，产品事件处理器由真实ConfigFile.Reload调用，不由探针代替执行。
        if (reloadActions.ValueKind != JsonValueKind.Array || reloadActions.GetArrayLength() > 32)
            throw new InvalidDataException("PLUGIN_PROBE_RELOAD_ACTIONS_INVALID");
        var ids = new HashSet<string>(StringComparer.Ordinal);
        foreach (var action in reloadActions.EnumerateArray())
        {
            if (action.ValueKind != JsonValueKind.Object || action.EnumerateObject().Count() != 2
                || !action.TryGetProperty("id", out var actionId) || actionId.ValueKind != JsonValueKind.String
                || string.IsNullOrWhiteSpace(actionId.GetString()) || !ids.Add(actionId.GetString()!)
                || !action.TryGetProperty("config_text", out var text) || text.ValueKind != JsonValueKind.String)
                throw new InvalidDataException("PLUGIN_PROBE_RELOAD_ACTION_INVALID");
        }
        EventHandler observedReload = (_, _) => reloadNotifications++;
        configType.GetEvent("ConfigReloaded")!.AddEventHandler(config, observedReload);
        foreach (var action in reloadActions.EnumerateArray())
        {
            string id = action.GetProperty("id").GetString()!;
            string configText = action.GetProperty("config_text").GetString()!;
            var beforeEntries = ReadEntries();
            int logsBefore = logs.Count, notificationsBefore = reloadNotifications;
            File.WriteAllText(configPath, configText, new System.Text.UTF8Encoding(false));
            string writtenHash = Hash(configPath);
            phase = "plugin_reload";
            reloadCalls++;
            configType.GetMethod("Reload", Type.EmptyTypes)!.Invoke(config, null);
            phase = "probe_observation";
            reloadObservations.Add(new { id, config_text = configText, written_config_sha256 = writtenHash,
                reload_call_index = reloadCalls, before_entries = beforeEntries, entries = ReadEntries(),
                logs_before = logsBefore, logs_after = logs.Count, logs = logs.Skip(logsBefore).ToArray(),
                config_reloaded_events = reloadNotifications - notificationsBefore,
                saved_config = File.ReadAllText(configPath), saved_config_sha256 = Hash(configPath) });
        }
    }
    Console.WriteLine(JsonSerializer.Serialize(new { status = "observed", process_id = Environment.ProcessId,
        plugin_type = pluginTypeName, plugin_load_calls = 1, plugin_instance_constructor_skipped = true,
        injected_base_properties = new[] { "Config", "Log" }, entries, logs = initialLogs,
        log_capture = "real_bepinex_global_listener_including_injected_base_log_source",
        config_save_called_by_probe = true,
        configuration_path = configPath, saved_config = initialSavedConfig,
        reload_protocol = "bepinex-config-reload-probe.v1", reload_observations = reloadObservations,
        config_reload_calls = reloadCalls, config_reloaded_events = reloadNotifications,
        final_entries = ReadEntries(), final_logs = logs.ToArray(), final_saved_config = File.ReadAllText(configPath),
        plugin_identity = metadata == null ? null : new {
            guid = Property(metadataType, metadata, "GUID")?.ToString(),
            name = Property(metadataType, metadata, "Name")?.ToString(),
            version = Property(metadataType, metadata, "Version")?.ToString() },
        target_api_methods_instrumented = false, file_watcher_started_by_probe = false,
        runtime_version = Environment.Version.ToString(),
        assembly_sha256 = Hash(assemblyPath),
        loaded_dependencies = AppDomain.CurrentDomain.GetAssemblies().Where(a => !a.IsDynamic &&
            dependencies.ContainsKey(a.GetName().Name!)).Select(a => new {
                name = a.GetName().Name, path = a.Location, sha256 = Hash(a.Location) }).ToArray(),
        scope = "cold_compiled_baseplugin_load_and_optional_real_config_reload_not_constructor_chainloader_watcher_or_game_runtime" }));
    return 0;
}
catch (Exception error)
{
    while ((error is TargetInvocationException || error is TypeInitializationException) && error.InnerException != null)
        error = error.InnerException;
    Console.WriteLine(JsonSerializer.Serialize(new { status = "execution_failed", execution_phase = phase,
        plugin_type = pluginTypeName, error_type = error.GetType().FullName, message = error.Message,
        stack_trace = error.StackTrace, process_id = Environment.ProcessId,
        scope = "cold_probe_failure_not_game_runtime" }));
    return 2;
}

public class ProbeLogListener : DispatchProxy
{
    public Action<object, object>? Capture;
    protected override object? Invoke(MethodInfo? method, object?[]? args)
    {
        if (method?.ReturnType.IsEnum == true) return Enum.ToObject(method.ReturnType, -1);
        if (method?.Name == "LogEvent" && args is { Length: 2 }) Capture!(args[0]!, args[1]!);
        return null;
    }
}
