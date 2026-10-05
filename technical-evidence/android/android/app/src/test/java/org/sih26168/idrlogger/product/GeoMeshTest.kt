package org.sih26168.idrlogger.product

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.sih26168.idrlogger.engine.NavigationSnapshot
import org.sih26168.idrlogger.engine.NavigationState

class GeoMeshTest {
    private fun snapshot(lat: Double, lon: Double) = NavigationSnapshot(state = NavigationState(sequenceId = 1, latitudeDeg = lat, longitudeDeg = lon))
    private fun zone(now: Long = 1_000L) = GeoFenceEntity().apply {
        id = "zone-1"; latitude = 12.9716; longitude = 77.5946; radiusMeters = 75.0
        category = GeoMeshCategory.POTHOLE.name; description = "Road damage"; createdAt = now; expiresAt = now + 10_000
    }

    @Test fun deterministicConfidenceRewardsConfirmationAndPenalizesDenialAndAge() {
        val now = 10 * 86_400_000L
        val base = GeoMeshConfidence.score(now, now, 0, 0, null)
        assertTrue(GeoMeshConfidence.score(now, now, 3, 0, now) > base)
        assertTrue(GeoMeshConfidence.score(now, now, 0, 2, null) < base)
        assertTrue(GeoMeshConfidence.score(0, now, 0, 0, null) < base)
    }

    @Test fun offlineEngineEmitsApproachEntryInsideExitAndRejectsExpiredZones() {
        val engine = GeoMeshEngine(); val now = 1_000L; val zone = zone(now)
        assertEquals(GeoMeshProximity.APPROACHING, engine.evaluate(snapshot(12.9730, 77.5946), listOf(zone), now).single().proximity)
        assertEquals(GeoMeshProximity.ENTERED, engine.evaluate(snapshot(12.9716, 77.5946), listOf(zone), now).single().proximity)
        assertEquals(GeoMeshProximity.INSIDE, engine.evaluate(snapshot(12.9716, 77.5946), listOf(zone), now).single().proximity)
        assertEquals(GeoMeshProximity.EXITED, engine.evaluate(snapshot(12.9750, 77.5946), listOf(zone), now).single().proximity)
        assertTrue(engine.evaluate(snapshot(12.9716, 77.5946), listOf(zone), zone.expiresAt).isEmpty())
    }

    @Test fun categoriesHaveFiniteSafetyExpiry() {
        assertTrue(GeoMeshCategory.entries.all { it.defaultLifetimeMs in 1..(30L * 86_400_000L) })
        assertTrue(GeoMeshCategory.ACCIDENT.defaultLifetimeMs < GeoMeshCategory.POTHOLE.defaultLifetimeMs)
    }
}
