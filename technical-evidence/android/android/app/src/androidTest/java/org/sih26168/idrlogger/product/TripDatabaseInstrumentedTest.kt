package org.sih26168.idrlogger.product

import androidx.room.Room
import androidx.test.core.app.ApplicationProvider
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

class TripDatabaseInstrumentedTest {
    private lateinit var database: NavGhostDatabase
    @Before fun setup() { database = Room.inMemoryDatabaseBuilder(ApplicationProvider.getApplicationContext(), NavGhostDatabase::class.java).allowMainThreadQueries().build() }
    @After fun close() = database.close()

    @Test fun daoStoresQueriesUpdatesAndCascadesTripData() {
        val dao = database.tripDao(); val trip = TripEntity().apply { startWallTimeMs = 100; title = "Drive" }
        val id = dao.insertTrip(trip); trip.id = id
        dao.insertSample(TripSampleEntity().apply { tripId = id; latitudeDeg = 12.0; longitudeDeg = 77.0; localizationMode = "GNSS_ACTIVE" })
        assertEquals("Drive", dao.trip(id).title); assertEquals(1, dao.samples(id).size)
        trip.status = "COMPLETED"; assertEquals(1, dao.updateTrip(trip)); assertEquals("COMPLETED", dao.trip(id).status)
        assertEquals(1, dao.deleteTrip(trip)); assertTrue(dao.samples(id).isEmpty())
    }
}
