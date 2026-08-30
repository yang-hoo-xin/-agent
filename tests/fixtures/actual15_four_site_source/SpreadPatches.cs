using BepInEx.Unity.IL2CPP.Utils.Collections;
using FirstPersonItem;
using GameData;
using Gear;
using HarmonyLib;
using Player;
using System;
using System.Collections;
using UnityEngine;

namespace AccurateCrosshair.CrosshairPatches
{
    [HarmonyPatch]
    internal static class SpreadPatches
    {
        private const float BASE_CROSSHAIR_SIZE = 20.0f; // The base size (from testing) that the crosshair should be at 90 FOV (when tan(FoV/2) = 1)
        private const float EXTRA_BUFFER_SIZE = 10.0f;   // Flat value added to account for the actual reticle, so as to not cover possible shot locations.
        public static bool isShotgun = false;
        private static bool _cachedAim = false;
        private static bool _validGun = false;

        public static CrosshairGuiLayer CrosshairLayer;
        private static float _crosshairSpeed;
        private static FirstPersonItemHolder? _cachedHolder;
        private static LerpingPairFloat? _cachedLookFoV;
        private static Coroutine? _smoothRoutine;
        private static float _spreadScalar = 1f;
        private static float _targetSpread;

#pragma warning disable CS8618
        static SpreadPatches()
        {
            Configuration.OnReload += OnConfigReload;
        }
#pragma warning restore CS8618


        private static void OnConfigReload()
        {
            if (CrosshairLayer != null)
            {
                CrosshairLayer.m_circleSpeed = _crosshairSpeed * Configuration.SpeedScalar;
                UpdateCrosshairSize();
            }
        }

        public static void UpdateSpreadScalar(float scalar)
        {
            _spreadScalar = scalar;
            UpdateCrosshairSize();
        }

        public static void UpdateCrosshairSize()
        {
            if (!_validGun) return;

            CrosshairLayer.ScaleToSize(CrosshairLayer.m_neutralCircleSize = GetCrosshairSize());
            if (Configuration.FirstShotType == FirstShotType.Inner)
                FirstShotGuiPatches.RefreshCrosshairSize();
        }

        public static void OnCleanup()
        {
            _cachedAim = false;
            _spreadScalar = 1f;
            _validGun = false;
        }

        [HarmonyPatch(typeof(FirstPersonItemHolder), nameof(FirstPersonItemHolder.Setup))]
        [HarmonyWrapSafe]
        [HarmonyPostfix]
        private static void UpdateCache(FirstPersonItemHolder __instance)
        {
            _cachedHolder = __instance;
            _cachedLookFoV = __instance.LookCamFov;
        }

        [HarmonyPatch(typeof(FPIS_Aim), nameof(FPIS_Aim.Enter))]
        [HarmonyWrapSafe]
        [HarmonyPostfix]
        private static void EnterAimState(FPIS_Aim __instance)
        {
            _cachedAim = true;
            if (__instance.Holder.WieldedItem.ItemDataBlock.ShowCrosshairWhenAiming)
                CrosshairLayer.ShowSpreadCircle(CrosshairLayer.m_dotSize);
            else if (_smoothRoutine != null)
            {
                CoroutineManager.StopCoroutine(_smoothRoutine);
                _smoothRoutine = null;
            }
        }

        [HarmonyPatch(typeof(FPIS_Aim), nameof(FPIS_Aim.Exit))]
        [HarmonyWrapSafe]
        [HarmonyPostfix]
        private static void ExitAimState()
        {
            _cachedAim = false;
        }

        [HarmonyPatch(typeof(CrosshairGuiLayer), nameof(CrosshairGuiLayer.ShowSpreadCircle))]
        [HarmonyWrapSafe]
        [HarmonyPrefix]
        private static void AdjustCrosshairSize(ref float crosshairSize)
        {
            if (!OverrideCrosshairSize(ref crosshairSize) && _smoothRoutine != null)
            {
                CoroutineManager.StopCoroutine(_smoothRoutine);
                _smoothRoutine = null;
            }
            else
                _smoothRoutine ??= CoroutineManager.StartCoroutine(ScaleSpreadCircle().WrapToIl2Cpp());
        }

        private static bool OverrideCrosshairSize(ref float crosshairSize)
        {
            _validGun = false;
            if (_cachedLookFoV == null) return false;

            if (Configuration.FirstShotType != FirstShotType.None)
                FirstShotPatches.ResetStoredCrosshair();

            PlayerAgent player = PlayerManager.GetLocalPlayerAgent();
            BulletWeapon? weapon = player.Inventory.m_wieldedItem?.TryCast<BulletWeapon>();
            if (weapon == null) return false;

            isShotgun = weapon.TryCast<Shotgun>() != null;

            ArchetypeDataBlock? archetypeData = weapon.ArchetypeData;
            if (archetypeData == null) return false;

            _validGun = true;
            float spread;
            if (isShotgun)
                spread = archetypeData.ShotgunConeSize + archetypeData.ShotgunBulletSpread;
            else
                spread = _cachedAim ? archetypeData.AimSpread : archetypeData.HipFireSpread;
            _targetSpread = spread;

            if (!isShotgun && Configuration.FirstShotType != FirstShotType.None)
                FirstShotPatches.SetStoredCrosshair(weapon);
            crosshairSize = GetCrosshairSize();

            return true;
        }

        private static IEnumerator ScaleSpreadCircle()
        {
            while (_validGun && _cachedLookFoV != null && _cachedLookFoV.CurrentLerp < 1f)
            {
                UpdateCrosshairSize();
                yield return null;
            }

            _smoothRoutine = null;
            if (_cachedLookFoV == null) yield break;
            UpdateCrosshairSize();
        }

        public static float GetCrosshairSize(float scalar)
        {
            scalar *= API.SpreadAPI.SpreadModifier;
            float sizeMultiplier = (float)(BASE_CROSSHAIR_SIZE / Math.Tan(Math.PI / 180.0 * _cachedLookFoV!.Current / 2));
            return Math.Max(Configuration.MinSize, _targetSpread * sizeMultiplier * scalar + EXTRA_BUFFER_SIZE);
        }

        public static float GetCrosshairSize() => GetCrosshairSize(_spreadScalar);

        [HarmonyPatch(typeof(CrosshairGuiLayer), nameof(CrosshairGuiLayer.Setup))]
        [HarmonyWrapSafe]
        [HarmonyPostfix]
        private static void AdjustResizeSpeed(CrosshairGuiLayer __instance)
        {
            CrosshairLayer = __instance;
            _crosshairSpeed = __instance.m_circleSpeed;
            __instance.m_circleSpeed *= Configuration.SpeedScalar;
        }
    }
}
