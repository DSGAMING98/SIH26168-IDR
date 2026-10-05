package org.sih26168.idrlogger.product

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import okhttp3.OkHttpClient
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer

class RouteNavigationTest {
    @Test fun droppedPinCreatesAnHonestCoordinateDestination() {
        val pin = DroppedPinDestination.create(12.65639, 77.40747)!!
        assertEquals("Dropped pin", pin.name)
        assertEquals("12.65639, 77.40747", pin.address)
        assertEquals(12.65639, pin.latitudeDeg, 0.0)
        assertEquals(77.40747, pin.longitudeDeg, 0.0)
    }

    @Test fun droppedPinRejectsInvalidCoordinates() {
        assertEquals(null, DroppedPinDestination.create(91.0, 77.0))
        assertEquals(null, DroppedPinDestination.create(12.0, Double.NaN))
    }

    @Test fun formatsRoadManeuversForVoiceGuidance() {
        assertEquals("Head north onto MG Road", RouteInstructionFormatter.format("depart", "north", "MG Road"))
        assertEquals("Turn right onto Brigade Road", RouteInstructionFormatter.format("turn", "right", "Brigade Road"))
        assertEquals("You have arrived at your destination", RouteInstructionFormatter.format("arrive", null, ""))
    }

    @Test fun progressAnnouncesEachManeuverOnlyOnce() {
        val route = fixtureRoute()
        val tracker = RouteProgressTracker(route)
        val first = tracker.update(RoutePoint(12.9716, 77.5946), 2.0, 3.0)
        val repeated = tracker.update(RoutePoint(12.9716, 77.5946), 2.0, 3.0)
        assertTrue(first.shouldSpeak)
        assertFalse(repeated.shouldSpeak)
        assertEquals(1, repeated.stepIndex)
    }

    @Test fun arrivalRespectsHonestUncertaintyRadius() {
        val route = fixtureRoute()
        val progress = RouteProgressTracker(route).update(RoutePoint(12.97501, 77.60001), 0.0, 5.0)
        assertTrue(progress.arrived)
        assertEquals("You have arrived at your destination", progress.instruction)
    }

    @Test(expected = IllegalArgumentException::class)
    fun rejectsInvalidRouteCoordinatesBeforeNetworkUse() {
        RouteDirectionsClient().routeBlocking(RoutePoint(95.0, 77.0), RoutePoint(12.0, 77.0))
    }

    @Test fun destinationSuggestionsUseCurrentPositionAsRankingBias() {
        MockWebServer().use { server ->
            server.enqueue(MockResponse().setResponseCode(200).setBody("[]"))
            val client = DestinationSearchClient(
                googleApiKey = "",
                client = OkHttpClient(),
                nominatimEndpoint = server.url("/search").toString(),
            )
            val latch = CountDownLatch(1)
            var result: Result<List<RouteDestination>>? = null
            client.search("Himalaya Hostel", RoutePoint(12.9716, 77.5946)) {
                result = it
                latch.countDown()
            }
            assertTrue(latch.await(2, TimeUnit.SECONDS))
            assertTrue(result!!.isSuccess)
            val request = server.takeRequest()
            val viewbox = request.requestUrl!!.queryParameter("viewbox")!!.split(',').map(String::toDouble)
            assertEquals(77.5946, (viewbox[0] + viewbox[2]) / 2.0, 1e-9)
            assertEquals(12.9716, (viewbox[1] + viewbox[3]) / 2.0, 1e-9)
            assertEquals("0", request.requestUrl!!.queryParameter("bounded"))
            client.close()
        }
    }

    private fun fixtureRoute() = NavigationRoute(
        points = listOf(RoutePoint(12.9716, 77.5946), RoutePoint(12.9720, 77.5950), RoutePoint(12.9750, 77.6000)),
        steps = listOf(
            RouteStep("Head north onto MG Road", RoutePoint(12.9716, 77.5946), 300.0),
            RouteStep("Turn right onto Brigade Road", RoutePoint(12.9720, 77.5950), 950.5),
            RouteStep("You have arrived at your destination", RoutePoint(12.9750, 77.6000), 0.0),
        ),
        distanceM = 1250.5,
        durationSeconds = 185.0,
    )
}
