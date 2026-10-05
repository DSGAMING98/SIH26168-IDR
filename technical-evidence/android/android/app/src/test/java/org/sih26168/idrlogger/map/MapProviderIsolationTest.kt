package org.sih26168.idrlogger.map

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import org.sih26168.idrlogger.engine.NavigationSnapshot
import org.sih26168.idrlogger.engine.NavigationState

class MapProviderIsolationTest {
    @Test fun offlineProviderAlwaysSuppliesAUsableCredentialFreeFallback() {
        val provider = MapProviderRegistry.competitionDefault()
        val presentation = provider.presentation()
        assertEquals(MapAvailability.LOCAL_READY, presentation.availability)
        assertEquals("local_enu", presentation.providerId)
        assertTrue(presentation.detailLabel.contains("LOCAL VIEW"))
        assertFalse(presentation.primaryLabel.contains("GOOGLE"))
    }

    @Test fun mapProviderCannotInjectOrOverrideEstimatorMarker() {
        val snapshot = NavigationSnapshot(
            state = NavigationState(eastM = 12.5, northM = -8.0, latitudeDeg = 12.34, longitudeDeg = 77.56, headingDeg = 91.0)
        )
        val beforeProvider = EngineMarkerPolicy.from(snapshot)
        MapProviderRegistry.competitionDefault().presentation()
        val afterProvider = EngineMarkerPolicy.from(snapshot)
        assertEquals(beforeProvider, afterProvider)
        assertEquals(12.5, afterProvider.eastM, 0.0)
        assertEquals(-8.0, afterProvider.northM, 0.0)
        assertEquals(12.34, afterProvider.latitudeDeg!!, 0.0)
    }

    @Test fun missingConfigurationAlwaysChoosesCredentialFreeFallback() {
        val presentation = GoogleMapsProvider(configured = false, servicesAvailable = true).presentation()
        assertEquals("local_enu", presentation.providerId)
        assertEquals(MapAvailability.LOCAL_READY, presentation.availability)
    }

    @Test fun unavailableGoogleServicesNeverDisableLocalNavigation() {
        val presentation = GoogleMapsProvider(configured = true, servicesAvailable = false).presentation()
        assertEquals(MapAvailability.NETWORK_UNAVAILABLE, presentation.availability)
        assertTrue(presentation.detailLabel.contains("NAVIGATION ACTIVE"))
    }

    @Test fun configuredGoogleProviderStartsWithoutAnyLocationInjectionSurface() {
        val presentation = MapProviderRegistry.competitionDefault(mapsConfigured = true, servicesAvailable = true).presentation()
        assertEquals("google_maps", presentation.providerId)
        assertEquals(MapAvailability.INITIALIZING, presentation.availability)
        assertEquals("Google", presentation.attribution)
        assertEquals(listOf("getId", "presentation"), MapProvider::class.java.declaredMethods.map { it.name }.sorted())
    }
}
