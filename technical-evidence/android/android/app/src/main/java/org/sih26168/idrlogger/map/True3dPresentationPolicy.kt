package org.sih26168.idrlogger.map

import kotlin.math.PI
import kotlin.math.cos
import kotlin.math.sin

enum class NavGhostRenderer { GOOGLE_3D, MAPLIBRE_3D, GOOGLE_LEGACY, LOCAL_ENU }

/**
 * Keeps the Maps 3D SurfaceView off device families where field testing proved that its
 * buffer queue cannot keep up.  This is deliberately narrow: unknown devices retain Google
 * 3D, while the affected phone uses the fully interactive MapLibre vector renderer instead.
 */
object Google3dCompatibilityPolicy {
    fun supports(manufacturer: String?, model: String?, hardware: String?): Boolean {
        val maker = manufacturer.orEmpty().trim().lowercase()
        val deviceModel = model.orEmpty().trim().lowercase()
        val chipset = hardware.orEmpty().trim().lowercase()
        val affectedVivoV60e = maker == "vivo" && (deviceModel == "v2513" || chipset == "mt6878")
        return !affectedVivoV60e
    }
}

/** Small deterministic renderer state policy; it has no access to engine or map coordinates. */
class RendererSelectionPolicy(initial: NavGhostRenderer = NavGhostRenderer.GOOGLE_3D) {
    var active: NavGhostRenderer = initial
        private set

    fun select(renderer: NavGhostRenderer) { active = renderer }
    fun onGoogle3dFailure(): NavGhostRenderer = NavGhostRenderer.MAPLIBRE_3D.also(::select)
    fun onMapLibreFailure(googleSupported: Boolean): NavGhostRenderer =
        (if (googleSupported) NavGhostRenderer.GOOGLE_LEGACY else NavGhostRenderer.LOCAL_ENU).also(::select)
}

/** Visible manual cycle: every tap selects a different renderer, never an invisible AUTO step. */
object ManualRendererCycle {
    fun next(active: NavGhostRenderer, maps3dConfigured: Boolean): NavGhostRenderer = when (active) {
        NavGhostRenderer.MAPLIBRE_3D -> NavGhostRenderer.GOOGLE_LEGACY
        NavGhostRenderer.GOOGLE_LEGACY -> if (maps3dConfigured) NavGhostRenderer.GOOGLE_3D else NavGhostRenderer.LOCAL_ENU
        NavGhostRenderer.GOOGLE_3D -> NavGhostRenderer.LOCAL_ENU
        NavGhostRenderer.LOCAL_ENU -> NavGhostRenderer.MAPLIBRE_3D
    }
}

data class LocalRingPoint(val eastM: Double, val northM: Double)

object True3dUncertaintyPolicy {
    fun ring(radiusM: Double?, segments: Int = 48): List<LocalRingPoint> {
        if (radiusM == null || !radiusM.isFinite() || radiusM <= 0.0 || segments < 8) return emptyList()
        return (0..segments).map { index ->
            val angle = index * 2.0 * PI / segments
            LocalRingPoint(radiusM * sin(angle), radiusM * cos(angle))
        }
    }
}
