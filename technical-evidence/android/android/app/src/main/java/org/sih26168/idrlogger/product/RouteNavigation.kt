package org.sih26168.idrlogger.product

import java.util.Locale
import java.util.concurrent.Executors
import kotlin.math.max
import kotlin.math.min
import okhttp3.HttpUrl.Companion.toHttpUrl
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONArray
import org.json.JSONObject
import org.sih26168.idrlogger.BuildConfig

data class RoutePoint(val latitudeDeg: Double, val longitudeDeg: Double)

data class RouteDestination(
    val name: String,
    val address: String,
    val latitudeDeg: Double,
    val longitudeDeg: Double,
)

object DroppedPinDestination {
    fun create(latitude: Double, longitude: Double): RouteDestination? {
        if (!latitude.isFinite() || !longitude.isFinite() || latitude !in -90.0..90.0 || longitude !in -180.0..180.0) return null
        val coordinates = String.format(Locale.US, "%.5f, %.5f", latitude, longitude)
        return RouteDestination("Dropped pin", coordinates, latitude, longitude)
    }
}

data class RouteStep(
    val instruction: String,
    val location: RoutePoint,
    val distanceM: Double,
)

data class NavigationRoute(
    val points: List<RoutePoint>,
    val steps: List<RouteStep>,
    val distanceM: Double,
    val durationSeconds: Double,
)

object RouteInstructionFormatter {
    fun format(type: String, modifier: String?, roadName: String): String {
        val road = roadName.trim().takeIf(String::isNotEmpty)?.let { " onto $it" }.orEmpty()
        val direction = modifier.orEmpty().replace('_', ' ').trim()
        return when (type.lowercase(Locale.US)) {
            "depart" -> if (direction.isBlank()) "Start driving$road" else "Head $direction$road"
            "arrive" -> "You have arrived at your destination"
            "roundabout", "rotary" -> "Enter the roundabout$road"
            "merge" -> "Merge ${direction.ifBlank { "ahead" }}$road"
            "fork" -> "Keep ${direction.ifBlank { "ahead" }}$road"
            "on ramp", "off ramp" -> "Take the ${direction.ifBlank { "ramp" }} ramp$road"
            "continue", "new name", "notification" -> "Continue ${direction.ifBlank { "straight" }}$road"
            "end of road" -> "At the end of the road, turn ${direction.ifBlank { "ahead" }}$road"
            else -> if (direction.isBlank() || direction == "straight") "Continue straight$road" else "Turn $direction$road"
        }.replace(Regex("\\s+"), " ").trim()
    }
}

object OsrmRouteParser {
    fun parse(payload: String): NavigationRoute {
        val root = JSONObject(payload)
        require(root.optString("code") == "Ok") { root.optString("message", "No route found") }
        val route = root.getJSONArray("routes").getJSONObject(0)
        val coordinates = route.getJSONObject("geometry").getJSONArray("coordinates")
        val points = (0 until coordinates.length()).map { index ->
            val pair = coordinates.getJSONArray(index)
            RoutePoint(pair.getDouble(1), pair.getDouble(0))
        }
        require(points.size >= 2) { "Route geometry is empty" }
        val steps = mutableListOf<RouteStep>()
        val legs = route.optJSONArray("legs") ?: JSONArray()
        for (legIndex in 0 until legs.length()) {
            val legSteps = legs.getJSONObject(legIndex).optJSONArray("steps") ?: continue
            for (stepIndex in 0 until legSteps.length()) {
                val step = legSteps.getJSONObject(stepIndex)
                val maneuver = step.getJSONObject("maneuver")
                val location = maneuver.getJSONArray("location")
                steps += RouteStep(
                    instruction = RouteInstructionFormatter.format(
                        maneuver.optString("type"),
                        maneuver.optString("modifier").takeIf(String::isNotBlank),
                        step.optString("name"),
                    ),
                    location = RoutePoint(location.getDouble(1), location.getDouble(0)),
                    distanceM = step.optDouble("distance", 0.0).coerceAtLeast(0.0),
                )
            }
        }
        return NavigationRoute(
            points = points,
            steps = steps,
            distanceM = route.getDouble("distance"),
            durationSeconds = route.getDouble("duration"),
        )
    }
}

class RouteDirectionsClient(
    private val client: OkHttpClient = OkHttpClient(),
    private val endpoint: String = "https://router.project-osrm.org",
) {
    private val executor = Executors.newSingleThreadExecutor()

    fun close() = executor.shutdownNow()

    fun route(origin: RoutePoint, destination: RoutePoint, callback: (Result<NavigationRoute>) -> Unit) {
        executor.execute { callback(runCatching { routeBlocking(origin, destination) }) }
    }

    internal fun routeBlocking(origin: RoutePoint, destination: RoutePoint): NavigationRoute {
        require(valid(origin) && valid(destination)) { "Route coordinates are invalid" }
        val coordinates = "${origin.longitudeDeg},${origin.latitudeDeg};${destination.longitudeDeg},${destination.latitudeDeg}"
        val url = "$endpoint/route/v1/driving/$coordinates".toHttpUrl().newBuilder()
            .addQueryParameter("alternatives", "false")
            .addQueryParameter("steps", "true")
            .addQueryParameter("geometries", "geojson")
            .addQueryParameter("overview", "full")
            .build()
        val request = Request.Builder().url(url).header("User-Agent", "NavGhost/2.2 (SIH26168; in-app navigation)").build()
        return client.newCall(request).execute().use { response ->
            if (!response.isSuccessful) error("Routing service returned ${response.code}")
            OsrmRouteParser.parse(response.body?.string().orEmpty())
        }
    }

    private fun valid(point: RoutePoint) = point.latitudeDeg.isFinite() && point.longitudeDeg.isFinite() &&
        point.latitudeDeg in -90.0..90.0 && point.longitudeDeg in -180.0..180.0
}

class DestinationSearchClient(
    private val googleApiKey: String,
    private val client: OkHttpClient = OkHttpClient(),
    private val androidPackage: String? = null,
    private val androidCertSha1: String? = null,
    private val nominatimEndpoint: String = "https://nominatim.openstreetmap.org/search",
) {
    private val executor = Executors.newSingleThreadExecutor()

    fun close() = executor.shutdownNow()

    fun search(query: String, bias: RoutePoint?, callback: (Result<List<RouteDestination>>) -> Unit) {
        val cleaned = query.trim()
        if (cleaned.length < 2) {
            callback(Result.failure(IllegalArgumentException("Enter at least two characters")))
            return
        }
        executor.execute {
            callback(runCatching {
                if (googleApiKey.isNotBlank()) runCatching { searchGoogle(cleaned, bias) }.getOrElse { searchOpenStreetMap(cleaned, bias) }
                else searchOpenStreetMap(cleaned, bias)
            }.map { results -> results.distinctBy { it.address.trim().lowercase(Locale.US) }.take(6) })
        }
    }

    private fun searchGoogle(query: String, bias: RoutePoint?): List<RouteDestination> {
        val body = JSONObject().apply {
            put("textQuery", query)
            put("maxResultCount", 6)
            if (bias != null) put("locationBias", JSONObject().put("circle", JSONObject()
                .put("center", JSONObject().put("latitude", bias.latitudeDeg).put("longitude", bias.longitudeDeg))
                .put("radius", 50_000.0)))
        }
        val builder = Request.Builder().url("https://places.googleapis.com/v1/places:searchText")
            .header("X-Goog-Api-Key", googleApiKey)
            .header("X-Goog-FieldMask", "places.displayName,places.formattedAddress,places.location")
            .post(body.toString().toRequestBody(JSON))
        androidPackage?.takeIf(String::isNotBlank)?.let { builder.header("X-Android-Package", it) }
        androidCertSha1?.takeIf(String::isNotBlank)?.let { builder.header("X-Android-Cert", it) }
        return client.newCall(builder.build()).execute().use { response ->
            if (!response.isSuccessful) error("Destination search returned ${response.code}")
            val places = JSONObject(response.body?.string().orEmpty()).optJSONArray("places") ?: JSONArray()
            (0 until places.length()).mapNotNull { index ->
                val place = places.optJSONObject(index) ?: return@mapNotNull null
                val location = place.optJSONObject("location") ?: return@mapNotNull null
                destination(
                    place.optJSONObject("displayName")?.optString("text").orEmpty(),
                    place.optString("formattedAddress"),
                    location.optDouble("latitude", Double.NaN),
                    location.optDouble("longitude", Double.NaN),
                )
            }
        }
    }

    private fun searchOpenStreetMap(query: String, bias: RoutePoint?): List<RouteDestination> {
        val builder = nominatimEndpoint.toHttpUrl().newBuilder()
            .addQueryParameter("q", query)
            .addQueryParameter("format", "jsonv2")
            .addQueryParameter("addressdetails", "0")
            .addQueryParameter("limit", "6")
            .addQueryParameter("accept-language", Locale.getDefault().toLanguageTag())
        bias?.takeIf { it.latitudeDeg.isFinite() && it.longitudeDeg.isFinite() }?.let {
            val latitudeRadius = 0.45
            val longitudeRadius = 0.45
            builder.addQueryParameter(
                "viewbox",
                "${it.longitudeDeg - longitudeRadius},${it.latitudeDeg + latitudeRadius},${it.longitudeDeg + longitudeRadius},${it.latitudeDeg - latitudeRadius}",
            )
            builder.addQueryParameter("bounded", "0")
        }
        val request = Request.Builder().url(builder.build())
            .header("User-Agent", "NavGhost/${BuildConfig.VERSION_NAME} (destination search)")
            .build()
        return client.newCall(request).execute().use { response ->
            if (!response.isSuccessful) error("Destination search returned ${response.code}")
            val results = JSONArray(response.body?.string().orEmpty())
            (0 until results.length()).mapNotNull { index ->
                val item = results.optJSONObject(index) ?: return@mapNotNull null
                val display = item.optString("display_name")
                destination(display.substringBefore(',').trim(), display, item.optString("lat").toDoubleOrNull() ?: Double.NaN,
                    item.optString("lon").toDoubleOrNull() ?: Double.NaN)
            }
        }
    }

    private fun destination(name: String, address: String, latitude: Double, longitude: Double): RouteDestination? {
        if (!latitude.isFinite() || !longitude.isFinite() || latitude !in -90.0..90.0 || longitude !in -180.0..180.0) return null
        return RouteDestination(name.ifBlank { address.substringBefore(',').ifBlank { "Destination" } }, address, latitude, longitude)
    }

    companion object { private val JSON = "application/json; charset=utf-8".toMediaType() }
}

data class RouteProgress(
    val stepIndex: Int,
    val instruction: String,
    val distanceToManeuverM: Double,
    val offRouteDistanceM: Double,
    val shouldSpeak: Boolean,
    val arrived: Boolean,
)

class RouteProgressTracker(private val route: NavigationRoute) {
    private var stepIndex = 0
    private val spoken = mutableSetOf<Int>()

    fun update(position: RoutePoint, speedMps: Double, uncertaintyM: Double?): RouteProgress {
        val offRoute = route.points.minOf { distanceM(position, it) }
        val arrivalDistance = distanceM(position, route.points.last())
        val arrivalThreshold = min(35.0, max(18.0, uncertaintyM?.coerceAtLeast(0.0) ?: 0.0))
        if (arrivalDistance <= arrivalThreshold) {
            return RouteProgress(route.steps.lastIndex.coerceAtLeast(0), "You have arrived at your destination", arrivalDistance, offRoute, spoken.add(Int.MAX_VALUE), true)
        }
        if (route.steps.isEmpty()) return RouteProgress(0, "Continue on the route", arrivalDistance, offRoute, false, false)
        stepIndex = stepIndex.coerceIn(0, route.steps.lastIndex)
        var distance = distanceM(position, route.steps[stepIndex].location)
        val trigger = max(24.0, speedMps.coerceAtLeast(0.0) * 6.0)
        val shouldSpeak = distance <= trigger && spoken.add(stepIndex)
        val instruction = route.steps[stepIndex].instruction
        if (shouldSpeak && stepIndex < route.steps.lastIndex) {
            stepIndex += 1
            distance = distanceM(position, route.steps[stepIndex].location)
        }
        return RouteProgress(stepIndex, instruction, distance, offRoute, shouldSpeak, false)
    }

    companion object {
        fun distanceM(a: RoutePoint, b: RoutePoint): Double =
            NearbyPlacesClient.distanceM(a.latitudeDeg, a.longitudeDeg, b.latitudeDeg, b.longitudeDeg)
    }
}
