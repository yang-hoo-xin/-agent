using System;
using System.IO;
using AccurateCrosshair.CrosshairPatches;
using BepInEx;
using BepInEx.Configuration;
using GTFO.API.Utilities;

namespace AccurateCrosshair
{
    public static class Configuration
    {
        public static bool FollowsRecoil { get; private set; } = true;
        public static FirstShotType FirstShotType { get; private set; } = FirstShotType.Inner;
        public static float FirstShotMinDelay { get; private set; } = 0.15f;
        public static bool PopEnabled { get; private set; } = false;
        public static float MinSize { get; private set; } = 10.0f;
        public static float SpeedScalar { get; private set; } = 1.0f;

        public static event Action? OnReload;

        private readonly static ConfigFile configFile;

        static Configuration()
        {
            configFile = new ConfigFile(Path.Combine(Paths.ConfigPath, Loader.MODNAME + ".cfg"), saveOnInit: true);
            BindAll(configFile);
        }

        internal static void Init()
        {
            LiveEditListener listener = LiveEdit.CreateListener(Paths.ConfigPath, Loader.MODNAME + ".cfg", false);
            listener.FileChanged += OnFileChanged;
        }

        private static void OnFileChanged(LiveEditEventArgs _)
        {
            configFile.Reload();
            string section = "General Settings";
            FollowsRecoil = (bool)configFile[section, "Follow Recoil"].BoxedValue;
            FirstShotType = (FirstShotType)configFile[section, "First Shot Display Mode"].BoxedValue;
            FirstShotMinDelay = (float)configFile[section, "First Shot Min Delay"].BoxedValue;
            PopEnabled = (bool)configFile[section, "Pop Enabled"].BoxedValue;
            MinSize = (float)configFile[section, "Minimum Size"].BoxedValue;
            SpeedScalar = (float)configFile[section, "Resize Modifier"].BoxedValue;
            if (SpeedScalar <= 0) SpeedScalar = 1.0f;

            OnReload?.Invoke();
        }

        private static void BindAll(ConfigFile config)
        {
            string section = "General Settings";
            string key = "Follow Recoil";
            string description = "Enables or disables the crosshair moving to match weapon recoil that is independent of your aim.";
            FollowsRecoil = config.Bind(section, key, FollowsRecoil, description).Value;

            key = "First Shot Display Mode";
            description = "Determines how the crosshair shows the hidden bonus accuracy after waiting 2 seconds to shoot.\r\nInner: Shows another circle. Match: Reduces crosshair size to match. None: Turns this off.";
            FirstShotType = config.Bind(section, key, FirstShotType, description).Value;

            key = "First Shot Min Delay";
            description = "If First Shot Display Mode is set to Match, the minimum shot delay non-semi automatic weapons need for the first shot effect to appear.";
            FirstShotMinDelay = config.Bind(section, key, FirstShotMinDelay, description).Value;

            key = "Pop Enabled";
            description = "Enables or disables the visual crosshair bloom when shooting.\r\nNote: Pop is not scaled to the accurate size and may be disproportionately large.";
            PopEnabled = config.Bind(section, key, PopEnabled, description).Value;

            key = "Minimum Size";
            description = "The minimum size of the reticle. Does not scale with field of view.\r\nNote: Cannot be smaller than 10.";
            MinSize = config.Bind(section, key, MinSize, description).Value;

            key = "Resize Modifier";
            description = "Scalar applied to the speed at which the crosshair resizes to its target spread.\r\nNote: Must be larger than 0. Does not affect the resize speed of pop.";
            SpeedScalar = config.Bind(section, key, SpeedScalar, description).Value;

            if (SpeedScalar <= 0) SpeedScalar = 1.0f;
        }
    }
}
