package org.sih26168.idrlogger.product

import androidx.room.Room
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Test

class GeoMeshDatabaseInstrumentedTest {
    @Test fun zoneAndPendingUploadPersistOffline() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val db = Room.inMemoryDatabaseBuilder(context, NavGhostDatabase::class.java).allowMainThreadQueries().build()
        try {
            val now = System.currentTimeMillis(); val zone = GeoFenceEntity().apply {
                id = "offline-zone"; latitude = 12.97; longitude = 77.59; radiusMeters = 75.0
                category = "ROAD_BLOCK"; description = "Local test"; createdAt = now; expiresAt = now + 10_000
                confidence = 45
            }
            db.geoMeshDao().upsert(zone)
            db.geoMeshDao().enqueue(GeoMeshPendingActionEntity().apply { geofenceId = zone.id; action = "CREATE"; createdAt = now })
            assertNotNull(db.geoMeshDao().byId(zone.id)); assertEquals(1, db.geoMeshDao().pendingCount())
            assertEquals(1, db.geoMeshDao().active(now).size)
            assertEquals(0, db.geoMeshDao().active(zone.expiresAt).size)
        } finally { db.close() }
    }

    @Test fun backendFailureKeepsQueuedActionAndReturnsOfflineState() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val db = Room.inMemoryDatabaseBuilder(context, NavGhostDatabase::class.java).allowMainThreadQueries().build()
        try {
            val now = System.currentTimeMillis(); val zone = GeoFenceEntity().apply {
                id = "offline-sync-zone"; latitude = 12.97; longitude = 77.59; radiusMeters = 75.0
                category = "ROAD_BLOCK"; description = "Offline sync test"; createdAt = now; expiresAt = now + 10_000
                confidence = 45
            }
            db.geoMeshDao().upsert(zone)
            db.geoMeshDao().enqueue(GeoMeshPendingActionEntity().apply { geofenceId = zone.id; action = "CREATE"; createdAt = now })
            val result = GeoMeshSyncManager(db.geoMeshDao(), GeoMeshApiClient("http://127.0.0.1:9")).sync(
                NearbyAnchor(zone.latitude, zone.longitude, 1L)
            )
            assertEquals(GeoMeshConnectionState.BACKEND_UNAVAILABLE, result.state)
            assertEquals(1, db.geoMeshDao().pendingCount())
            assertTrue(db.geoMeshDao().active(now).isNotEmpty())
        } finally { db.close() }
    }
}
