package org.sih26168.idrlogger.product

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Assert.assertEquals
import org.junit.Test
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.sih26168.idrlogger.engine.NavigationSnapshot
import org.sih26168.idrlogger.engine.NavigationState
import org.sih26168.idrlogger.engine.IdrEngine

class NearbyPolicyTest {
    @Test fun sourceIsExactlyNavigationSnapshotEstimate() {
        val snapshot = NavigationSnapshot(state = NavigationState(sequenceId = 42, latitudeDeg = 12.34, longitudeDeg = 77.56))
        val result = NearbyQueryFactory.from(snapshot) as NearbyQueryResult.Ready
        assertTrue(result.anchor.latitudeDeg == 12.34 && result.anchor.longitudeDeg == 77.56 && result.anchor.snapshotSequenceId == 42L)
    }

    @Test fun missingEstimatorPositionIsRejectedWithoutFallback() {
        assertTrue(NearbyQueryFactory.from(NavigationSnapshot()) is NearbyQueryResult.Unavailable)
    }

    @Test fun repeatedRequestsAreThrottledDeterministically() {
        val gate = NearbyRequestGate(3000)
        assertTrue(gate.permit(1000)); assertFalse(gate.permit(3999)); assertTrue(gate.permit(4000))
    }

    @Test fun nearbyProviderHasNoEstimatorMutationBoundary() {
        assertFalse(NearbyPlacesClient::class.java.declaredMethods.any { method -> method.parameterTypes.contains(IdrEngine::class.java) })
    }

    @Test fun missingGoogleConfigurationSelectsLiveOsmFallback() {
        assertEquals("OpenStreetMap / Overpass", NearbyPlacesClient("").providerName)
    }

    @Test fun overpassSuccessUsesSnapshotCoordinates() {
        MockWebServer().use { server ->
            server.enqueue(MockResponse().setResponseCode(200).setBody("{\"elements\":[]}"))
            val client = NearbyPlacesClient("", client = okhttp3.OkHttpClient(), overpassEndpoint = server.url("/api/interpreter").toString())
            val latch = CountDownLatch(1); var result: Result<List<NearbyPlace>>? = null
            client.search(NearbyAnchor(12.9716, 77.5946, 7), "hospital", "") { result = it; latch.countDown() }
            assertTrue(latch.await(2, TimeUnit.SECONDS))
            assertTrue(result!!.getOrThrow().isEmpty())
            assertTrue(server.takeRequest().body.readUtf8().contains("12.9716%2C77.5946"))
        }
    }

    @Test fun straightLineDistanceIsGeodesicAndFinite() {
        val metres = NearbyPlacesClient.distanceM(12.9716, 77.5946, 12.9726, 77.5946)
        assertTrue(metres in 110.0..112.0)
    }

    @Test fun nameSearchQueriesLivePlacesWithoutChoosingACategory() {
        MockWebServer().use { server ->
            server.enqueue(MockResponse().setResponseCode(200).setBody(
                """{"elements":[{"lat":12.9717,"lon":77.5947,"tags":{"name":"Campus Cafe","amenity":"cafe"}}]}""",
            ))
            val client = NearbyPlacesClient("", overpassEndpoint = server.url("/api/interpreter").toString())
            val latch = CountDownLatch(1); var result: Result<List<NearbyPlace>>? = null
            client.search(NearbyAnchor(12.9716, 77.5946, 8), NearbyPlacesClient.SEARCH_ALL_CATEGORY, "Campus") {
                result = it; latch.countDown()
            }
            assertTrue(latch.await(2, TimeUnit.SECONDS))
            assertTrue(result!!.isSuccess)
            val requestBody = server.takeRequest().body.readUtf8()
            assertTrue(requestBody.contains("around%3A5000"))
            assertTrue(requestBody.contains("Campus"))
        }
    }

    @Test fun overpassEmptyAndNetworkFailureAreSafeResults() {
        MockWebServer().use { server ->
            server.enqueue(MockResponse().setResponseCode(200).setBody("{\"elements\":[]}"))
            server.enqueue(MockResponse().setResponseCode(503))
            val first = NearbyPlacesClient("", overpassEndpoint = server.url("/").toString())
            val emptyLatch = CountDownLatch(1); var empty: Result<List<NearbyPlace>>? = null
            first.search(NearbyAnchor(12.0, 77.0, 1), "atm", "") { empty = it; emptyLatch.countDown() }
            assertTrue(emptyLatch.await(2, TimeUnit.SECONDS)); assertTrue(empty!!.getOrThrow().isEmpty())
            val second = NearbyPlacesClient("", overpassEndpoint = server.url("/").toString())
            val errorLatch = CountDownLatch(1); var failed: Result<List<NearbyPlace>>? = null
            second.search(NearbyAnchor(12.0, 77.0, 2), "atm", "") { failed = it; errorLatch.countDown() }
            assertTrue(errorLatch.await(2, TimeUnit.SECONDS)); assertTrue(failed!!.isFailure)
        }
    }
}
