package org.sih26168.idrlogger.map

import kotlin.math.hypot
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class True3dPresentationPolicyTest {
    @Test fun manualCycleNeverStopsOnTheAlreadyVisibleRenderer() {
        assertEquals(NavGhostRenderer.GOOGLE_LEGACY, ManualRendererCycle.next(NavGhostRenderer.MAPLIBRE_3D, true))
        assertEquals(NavGhostRenderer.GOOGLE_3D, ManualRendererCycle.next(NavGhostRenderer.GOOGLE_LEGACY, true))
        assertEquals(NavGhostRenderer.LOCAL_ENU, ManualRendererCycle.next(NavGhostRenderer.GOOGLE_3D, true))
        assertEquals(NavGhostRenderer.MAPLIBRE_3D, ManualRendererCycle.next(NavGhostRenderer.LOCAL_ENU, true))
    }

    @Test fun manualCycleSkipsUnconfiguredGoogle3d() {
        assertEquals(NavGhostRenderer.LOCAL_ENU, ManualRendererCycle.next(NavGhostRenderer.GOOGLE_LEGACY, false))
    }

    @Test fun automaticFallbackOrderIsGoogle3dThenMapLibreThenGoogleLegacy() {
        val policy = RendererSelectionPolicy()
        assertEquals(NavGhostRenderer.GOOGLE_3D, policy.active)
        assertEquals(NavGhostRenderer.MAPLIBRE_3D, policy.onGoogle3dFailure())
        assertEquals(NavGhostRenderer.GOOGLE_LEGACY, policy.onMapLibreFailure(true))
        assertEquals(NavGhostRenderer.GOOGLE_LEGACY, policy.active)
    }

    @Test fun rendererFailureUsesLocalWithoutGoogle() {
        val policy = RendererSelectionPolicy()
        policy.onGoogle3dFailure()
        assertEquals(NavGhostRenderer.LOCAL_ENU, policy.onMapLibreFailure(false))
    }

    @Test fun fieldVerifiedVivoV60eUsesSafeVectorRenderer() {
        assertTrue(!Google3dCompatibilityPolicy.supports("vivo", "V2513", "mt6878"))
        assertTrue(!Google3dCompatibilityPolicy.supports("VIVO", "V2513", "unknown"))
    }

    @Test fun unknownAndCapableDevicesRetainGoogle3d() {
        assertTrue(Google3dCompatibilityPolicy.supports("Google", "Pixel 9", "komodo"))
        assertTrue(Google3dCompatibilityPolicy.supports(null, null, null))
    }

    @Test fun uncertaintyFootprintUsesEstimatorRadius() {
        val ring = True3dUncertaintyPolicy.ring(32.0)
        assertEquals(49, ring.size)
        ring.forEach { assertEquals(32.0, hypot(it.eastM, it.northM), 1e-8) }
        assertEquals(ring.first().eastM, ring.last().eastM, 1e-8)
        assertEquals(ring.first().northM, ring.last().northM, 1e-8)
    }

    @Test fun unavailableUncertaintyDoesNotInventHalo() {
        assertTrue(True3dUncertaintyPolicy.ring(null).isEmpty())
        assertTrue(True3dUncertaintyPolicy.ring(Double.NaN).isEmpty())
    }
}
