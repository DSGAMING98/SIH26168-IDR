package org.sih26168.idrlogger.product

import java.util.Locale
import java.util.concurrent.Executors
import kotlin.math.cos
import kotlin.math.max
import kotlin.math.min
import kotlin.math.PI
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

object CoordinateDestinationParser {
    private val coordinatePair = Regex("(?<![0-9.])(-?\\d{1,2}(?:\\.\\d+)?)\\s*[, ]\\s*(-?\\d{1,3}(?:\\.\\d+)?)(?![0-9.])")

    fun parse(query: String): RouteDestination? {
        val match = coordinatePair.find(query.trim()) ?: return null
        val latitude = match.groupValues[1].toDoubleOrNull() ?: return null
        val longitude = match.groupValues[2].toDoubleOrNull() ?: return null
        return DroppedPinDestination.create(latitude, longitude)
    }
}

/** Keeps only the untravelled route, beginning at the closest projection of the live position. */
object RouteProgressGeometry {
    fun remainingPolyline(points: List<RoutePoint>, position: RoutePoint): List<RoutePoint> {
        if (points.size < 2) return points
        val metresPerLatitudeDegree = 111_320.0
        val metresPerLongitudeDegree = metresPerLatitudeDegree * cos(position.latitudeDeg * PI / 180.0)
        var bestSegment = 0
        var bestDistanceSquared = Double.POSITIVE_INFINITY
        for (index in 0 until points.lastIndex) {
            val start = points[index]
            val end = points[index + 1]
            val startX = (start.longitudeDeg - position.longitudeDeg) * metresPerLongitudeDegree
            val startY = (start.latitudeDeg - position.latitudeDeg) * metresPerLatitudeDegree
            val endX = (end.longitudeDeg - position.longitudeDeg) * metresPerLongitudeDegree
            val endY = (end.latitudeDeg - position.latitudeDeg) * metresPerLatitudeDegree
            val dx = endX - startX
            val dy = endY - startY
            val lengthSquared = dx * dx + dy * dy
            val fraction = if (lengthSquared <= 1e-6) 0.0 else (-(startX * dx + startY * dy) / lengthSquared).coerceIn(0.0, 1.0)
            val projectedX = startX + fraction * dx
            val projectedY = startY + fraction * dy
            val distanceSquared = projectedX * projectedX + projectedY * projectedY
            if (distanceSquared < bestDistanceSquared) {
                bestDistanceSquared = distanceSquared
                bestSegment = index
            }
        }
        return buildList {
            // Start exactly under the live vehicle marker, then retain only points ahead.
            add(position)
            addAll(points.drop(bestSegment + 1))
        }.distinctBy { Pair(it.latitudeDeg, it.longitudeDeg) }
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
    private val googleEndpoint: String = "https://places.googleapis.com/v1/places:searchText",
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
                CoordinateDestinationParser.parse(cleaned)?.let { return@runCatching listOf(it) }
                val google = if (googleApiKey.isNotBlank()) runCatching { searchGoogle(cleaned, bias) } else null
                val openStreetMap = runCatching { searchOpenStreetMap(cleaned, bias) }
                val combined = google?.getOrDefault(emptyList()).orEmpty() + openStreetMap.getOrDefault(emptyList())
                if (combined.isEmpty()) {
                    google?.exceptionOrNull()?.let { throw it }
                    openStreetMap.exceptionOrNull()?.let { throw it }
                }
                rankAndDeduplicate(combined, cleaned, bias).take(10)
            })
        }
    }

    private fun searchGoogle(query: String, bias: RoutePoint?): List<RouteDestination> {
        val escapedQuery = query.replace("\\", "\\\\").replace("\"", "\\\"")
        val locationBias = bias?.let {
            ""","locationBias":{"circle":{"center":{"latitude":${it.latitudeDeg},"longitude":${it.longitudeDeg}},"radius":50000.0}}"""
        }.orEmpty()
        val body = """{"textQuery":"$escapedQuery","pageSize":12$locationBias}"""
        val builder = Request.Builder().url(googleEndpoint)
            .header("X-Goog-Api-Key", googleApiKey)
            .header("X-Goog-FieldMask", "places.displayName,places.formattedAddress,places.location")
            .post(body.toRequestBody(JSON))
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
            .addQueryParameter("addressdetails", "1")
            .addQueryParameter("namedetails", "1")
            .addQueryParameter("limit", "12")
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

    private fun rankAndDeduplicate(
        values: List<RouteDestination>,
        query: String,
        bias: RoutePoint?,
    ): List<RouteDestination> {
        val normalizedQuery = query.lowercase(Locale.US).replace(Regex("[^a-z0-9]+"), " ").trim()
        fun score(value: RouteDestination): Double {
            val name = value.name.lowercase(Locale.US).replace(Regex("[^a-z0-9]+"), " ").trim()
            val address = value.address.lowercase(Locale.US)
            val textScore = when {
                name == normalizedQuery -> 0.0
                name.startsWith(normalizedQuery) -> 1.0
                name.contains(normalizedQuery) -> 2.0
                address.contains(normalizedQuery) -> 3.0
                else -> 4.0
            }
            val distancePenalty = bias?.let {
                RouteProgressTracker.distanceM(it, RoutePoint(value.latitudeDeg, value.longitudeDeg)) / 1_000_000.0
            } ?: 0.0
            return textScore + distancePenalty
        }
        return values
            .distinctBy { "%.5f,%.5f".format(Locale.US, it.latitudeDeg, it.longitudeDeg) }
            .sortedBy(::score)
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
