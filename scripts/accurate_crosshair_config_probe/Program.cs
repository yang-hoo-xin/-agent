// Exercise the compiled Mod's real Configuration and real BepInEx ConfigFile.
// This does not initialize the plugin, Harmony, Unity or the LiveEdit watcher.
using System.Collections;
using System.Reflection;
using System.Runtime.Loader;
using System.Security.Cryptography;
using System.Text.Json;

static string Verify(JsonElement reference)
{
    string path = Path.GetFullPath(reference.GetProperty("path").GetString()!);
    string expected = reference.GetProperty("sha256").GetString()!;
    if (!Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(path))).Equals(expected, StringComparison.OrdinalIgnoreCase))
        throw new InvalidDataException("CONFIG_PROBE_FILE_HASH_CHANGED");
    return path;
}

static object? Property(Type type, object? target, string name)
{
    var property = type.GetProperty(name, BindingFlags.Static | BindingFlags.Instance | BindingFlags.Public);
    if (property == null) throw new MissingMemberException(type.FullName, name);
    var value = property.GetValue(target);
    return value is Enum ? value.ToString() : value;
}

string executionPhase = "probe_setup";
try
{
    using var input = JsonDocument.Parse(File.ReadAllBytes(args.Single()));
    var request = input.RootElement;
    var assemblyPath = Verify(request.GetProperty("assembly"));
    var sandbox = Path.GetFullPath(request.GetProperty("sandbox_root").GetString()!);
    if (!Directory.Exists(sandbox)) throw new DirectoryNotFoundException("CONFIG_PROBE_SANDBOX_REQUIRED");
    var dependencies = new Dictionary<string, string>(StringComparer.Ordinal);
    foreach (var reference in request.GetProperty("dependencies").EnumerateArray())
    {
        var path = Verify(reference);
        try
        {
            string name = AssemblyName.GetAssemblyName(path).Name!;
            if (dependencies.TryGetValue(name, out var other) &&
                !SHA256.HashData(File.ReadAllBytes(other)).SequenceEqual(SHA256.HashData(File.ReadAllBytes(path))))
                throw new InvalidDataException("CONFIG_PROBE_AMBIGUOUS_ASSEMBLY");
            dependencies[name] = path;
        }
        catch (BadImageFormatException) { } // Native DLLs are not managed resolver entries.
    }
    AssemblyLoadContext.Default.Resolving += (context, name) =>
        name.Name != null && dependencies.TryGetValue(name.Name, out var path)
            ? context.LoadFromAssemblyPath(path) : null;

    var core = AssemblyLoadContext.Default.LoadFromAssemblyPath(dependencies["BepInEx.Core"]);
    var paths = core.GetType("BepInEx.Paths", throwOnError: true)!;
    var setter = paths.GetMethod("SetExecutablePath", BindingFlags.Public | BindingFlags.Static,
        new[] { typeof(string), typeof(string), typeof(string), typeof(bool), typeof(string[]) })!;
    // Verified against the bound Paths.SetExecutablePath IL: executable,
    // BepInEx root, managed directory, game-data-from-managed flag, search dirs.
    setter.Invoke(null, new object?[] { Path.Combine(sandbox, "ConfigProbe.exe"),
        Path.Combine(sandbox, "BepInEx"), null, false, Array.Empty<string>() });
    var configDirectory = (string)Property(paths, null, "ConfigPath")!;
    var configPath = Path.Combine(configDirectory, "AccurateCrosshair.cfg");
    if (!Path.GetFullPath(configPath).StartsWith(sandbox + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase))
        throw new InvalidDataException("CONFIG_PROBE_PATH_ESCAPED");
    Directory.CreateDirectory(configDirectory);
    if (request.TryGetProperty("seed_config", out var seed) && seed.ValueKind == JsonValueKind.String)
        File.WriteAllText(configPath, seed.GetString());

    var mod = AssemblyLoadContext.Default.LoadFromAssemblyPath(assemblyPath);
    var configuration = mod.GetType("AccurateCrosshair.Configuration", throwOnError: true)!;
    var wanted = new[] { "AccurateSpreadEnabled", "FollowsRecoil", "FirstShotType", "FirstShotMinDelay",
        "PopEnabled", "MinSize", "SpeedScalar" };
    Dictionary<string, object?> ReadValues()
    {
        var values = new Dictionary<string, object?>();
        foreach (var name in wanted)
        {
            var property = configuration.GetProperty(name, BindingFlags.Public | BindingFlags.Static);
            values[name] = property == null ? null : Property(configuration, null, name);
        }
        return values;
    }
    executionPhase = "configuration_initialization";
    var initial = ReadValues(); // Invokes the actual compiled static initializer.
    executionPhase = "probe_observation";
    var configFile = configuration.GetField("configFile", BindingFlags.NonPublic | BindingFlags.Static)!.GetValue(null)!;
    var actualConfigPath = (string)Property(configFile.GetType(), configFile, "ConfigFilePath")!;
    if (!Path.GetFullPath(actualConfigPath).Equals(configPath, StringComparison.OrdinalIgnoreCase))
        throw new InvalidDataException("CONFIG_PROBE_UNEXPECTED_CONFIG_FILE");
    var keys = ((IEnumerable)Property(configFile.GetType(), configFile, "Keys")!).Cast<object>()
        .Select(key => new { section = Property(key.GetType(), key, "Section"), key = Property(key.GetType(), key, "Key") }).ToArray();
    object[] ReadEntries()
    {
        var indexer = configFile.GetType().GetProperty("Item", new[] { typeof(string), typeof(string) })!;
        return ((IEnumerable)Property(configFile.GetType(), configFile, "Keys")!).Cast<object>()
            .Select(key => {
                var section = (string)Property(key.GetType(), key, "Section")!;
                var label = (string)Property(key.GetType(), key, "Key")!;
                var entry = indexer.GetValue(configFile, new object[] { section, label })!;
                return (object)new { section, key = label, value = Property(entry.GetType(), entry, "BoxedValue") };
            }).ToArray();
    }
    var initialEntries = ReadEntries();
    int reloadEvents = 0;
    Dictionary<string, object?>? reloaded = null;
    if (request.TryGetProperty("reload_config", out var reload) && reload.ValueKind == JsonValueKind.String)
    {
        Action observed = () => reloadEvents++;
        configuration.GetEvent("OnReload", BindingFlags.Public | BindingFlags.Static)!.AddEventHandler(null, observed);
        File.WriteAllText(configPath, reload.GetString());
        var onChanged = configuration.GetMethod("OnFileChanged", BindingFlags.NonPublic | BindingFlags.Static)!;
        var eventType = onChanged.GetParameters().Single().ParameterType;
        var changed = Activator.CreateInstance(eventType)!;
        eventType.GetProperty("FullPath")!.SetValue(changed, configPath);
        eventType.GetProperty("FileName")!.SetValue(changed, Path.GetFileName(configPath));
        var kind = eventType.GetProperty("Type")!;
        kind.SetValue(changed, Enum.Parse(kind.PropertyType, "Changed", ignoreCase: false));
        executionPhase = "reload_consumer";
        onChanged.Invoke(null, new[] { changed });
        reloaded = ReadValues();
    }
    Console.WriteLine(JsonSerializer.Serialize(new { status = "observed", process_id = Environment.ProcessId,
        configuration_path = configPath, keys, initial, initial_entries = initialEntries,
        reloaded, final_entries = ReadEntries(), reload_events = reloadEvents,
        saved_config = File.ReadAllText(configPath), configuration_assembly_sha256 =
            Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(assemblyPath))).ToLowerInvariant(),
        config_library_sha256 = Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(dependencies["BepInEx.Core"]))).ToLowerInvariant(),
        scope = "real_config_file_and_reload_consumer_not_liveedit_watcher_or_game_runtime" }));
    return 0;
}
catch (Exception error)
{
    while ((error is TargetInvocationException || error is TypeInitializationException) && error.InnerException != null)
        error = error.InnerException;
    bool bodyFailed = (executionPhase == "configuration_initialization" || executionPhase == "reload_consumer")
        && (error.StackTrace ?? "").Contains("AccurateCrosshair.Configuration", StringComparison.Ordinal)
        && (error is KeyNotFoundException || error is NullReferenceException || error is ArgumentException);
    Console.WriteLine(JsonSerializer.Serialize(new { status = "execution_failed", error_type = error.GetType().FullName,
        message = error.Message, execution_phase = executionPhase,
        failure_owner = bodyFailed ? "patch_implementation" : "validator", process_id = Environment.ProcessId }));
    return 2;
}
