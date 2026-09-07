using AccurateCrosshair.CrosshairPatches;
using System.Collections.Generic;

namespace AccurateCrosshair.API
{
    public static class SpreadAPI
    {
        private static readonly Dictionary<object, float> _modifiers = new();

        public static float SpreadModifier { get; private set; } = 1f;

        public static void SetModifier(object key, float value)
        {
            _modifiers[key] = value;
            UpdateModifier();
        }
        public static void RemoveModifier(object key)
        {
            _modifiers.Remove(key);
            UpdateModifier();
        }

        private static void UpdateModifier()
        {
            float oldMod = SpreadModifier;
            SpreadModifier = 1f;
            foreach (var modifier in _modifiers.Values)
                SpreadModifier *= modifier;
            if (oldMod != SpreadModifier)
                SpreadPatches.UpdateCrosshairSize();
        }
    }
}
