package org.sih26168.idrlogger.product

import android.content.Context
import android.content.pm.PackageManager
import android.os.Build
import java.util.Locale
import java.security.MessageDigest
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.Executors
import kotlin.math.atan2
import kotlin.math.cos
import kotlin.math.sin
import kotlin.math.sqrt
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.FormBody
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONArray
import org.json.JSONObject
import org.sih26168.idrlogger.BuildConfig
import org.sih26168.idrlogger.engine.NavigationSnapshot

data class NearbyAnchor(val latitudeDeg: Double, val longitudeDeg: Double, val snapshotSequenceId: Long)
data class NearbyPlace(val name: String, val category: String, val latitudeDeg: Double, val longitudeDeg: Double, val rating: Double?, val distanceM: Double)
sealed class NearbyQueryResult {
    data class Ready(val anchor: NearbyAnchor) : NearbyQueryResult()
    data class Unavailable(val reason: String) : NearbyQueryResult()
}

/** This is the only nearby origin factory. It accepts estimator output, never LocationManager/FusedLocation/camera state. */
object NearbyQueryFactory {
    fun from(snapshot: NavigationSnapshot): NearbyQueryResult {
        val state = snapshot.state
        val lat = state.latitudeDeg
        val lon = state.longitudeDeg
        return if (state.sequenceId < 0 || lat == null || lon == null || !lat.isFinite() || !lon.isFinite() || lat !in -90.0..90.0 || lon !in -180.0..180.0)
            NearbyQueryResult.Unavailable("Start navigation and wait for a trusted NavGhost position.")
        else NearbyQueryResult.Ready(NearbyAnchor(lat, lon, state.sequenceId))
    }
}

class NearbyRequestGate(private val minimumIntervalMs: Long = 3_000L) {
    private var lastRequestMs = Long.MIN_VALUE
    @Synchronized fun permit(nowMs: Long): Boolean {
        if (lastRequestMs != Long.MIN_VALUE && nowMs - lastRequestMs < minimumIntervalMs) return false
        lastRequestMs = nowMs; return true
    }
}

class NearbyPlacesClient(
    private val apiKey: String,
    private val client: OkHttpClient = OkHttpClient(),
    private val androidPackage: String? = null,
    private val androidCertSha1: String? = null,
    private val overpassEndpoint: String = OVERPASS_ENDPOINT,
) {
    private data class Cached(val atMs: Long, val results: List<NearbyPlace>)
    private val executor = Executors.newSingleThreadExecutor()
    private val gate = NearbyRequestGate()
    private val cache = ConcurrentHashMap<String, Cached>()
    val providerName: String get() = if (apiKey.isBlank()) "OpenStreetMap / Overpass" else "Google Places"

    fun search(anchor: NearbyAnchor, category: String, query: String, nowMs: Long = System.currentTimeMillis(), callback: (Result<List<NearbyPlace>>) -> Unit) {
        if (!gate.permit(nowMs)) { callback(Result.failure(IllegalStateException("Please wait a moment before another search."))); return }
        val key = String.format(Locale.US, "%.3f:%.3f:%s:%s", anchor.latitudeDeg, anchor.longitudeDeg, category, query.trim().lowercase())
        cache[key]?.takeIf { nowMs - it.atMs < CACHE_MS }?.let { callback(Result.success(it.results)); return }
        executor.execute {
            callback(runCatching {
                if (apiKey.isBlank()) searchOverpass(anchor, category, query)
                else runCatching { searchGoogle(anchor, category, query) }.getOrElse { searchOverpass(anchor, category, query) }
            }
                .map { it.sortedBy(NearbyPlace::distanceM).take(MAX_RESULTS) }
                .onSuccess { cache[key] = Cached(nowMs, it) })
        }
    }

    private fun searchGoogle(anchor: NearbyAnchor, category: String, query: String): List<NearbyPlace> {
                val body = JSONObject().apply {
                    put("includedTypes", JSONArray().put(category))
                    put("maxResultCount", MAX_RESULTS)
                    put("rankPreference", "DISTANCE")
                    put("locationRestriction", JSONObject().put("circle", JSONObject()
                        .put("center", JSONObject().put("latitude", anchor.latitudeDeg).put("longitude", anchor.longitudeDeg))
                        .put("radius", 3000.0)))
                }
                val requestBuilder = Request.Builder().url("https://places.googleapis.com/v1/places:searchNearby")
                    .header("X-Goog-Api-Key", apiKey)
                    .header("X-Goog-FieldMask", "places.displayName,places.primaryType,places.location,places.rating")
                    .post(body.toString().toRequestBody(JSON))
                androidPackage?.takeIf(String::isNotBlank)?.let { requestBuilder.header("X-Android-Package", it) }
                androidCertSha1?.takeIf(String::isNotBlank)?.let { requestBuilder.header("X-Android-Cert", it) }
                val request = requestBuilder.build()
                return client.newCall(request).execute().use { response ->
                    if (!response.isSuccessful) error("Places service returned ${response.code}")
                    val array = JSONObject(response.body?.string().orEmpty()).optJSONArray("places") ?: JSONArray()
                    (0 until array.length()).mapNotNull { index ->
                        val place = array.optJSONObject(index) ?: return@mapNotNull null
                        val location = place.optJSONObject("location") ?: return@mapNotNull null
                        val lat = location.optDouble("latitude", Double.NaN); val lon = location.optDouble("longitude", Double.NaN)
                        if (!lat.isFinite() || !lon.isFinite()) return@mapNotNull null
                        val name = place.optJSONObject("displayName")?.optString("text")?.takeIf(String::isNotBlank) ?: "Nearby place"
                        if (query.isNotBlank() && !name.contains(query.trim(), ignoreCase = true)) return@mapNotNull null
                        NearbyPlace(name, place.optString("primaryType", category).replace('_', ' '), lat, lon,
                            place.optDouble("rating", Double.NaN).takeIf(Double::isFinite), distanceM(anchor.latitudeDeg, anchor.longitudeDeg, lat, lon))
                    }
                }
    }

    private fun searchOverpass(anchor: NearbyAnchor, category: String, query: String): List<NearbyPlace> {
        val statement = if (category == SEARCH_ALL_CATEGORY) {
            val safeQuery = query.trim().replace(Regex("[^\\p{L}\\p{N} &'\\-]"), "").take(80)
            require(safeQuery.length >= 2) { "Enter at least two letters to search by name." }
            "[out:json][timeout:18];nwr[\"name\"~\"$safeQuery\",i](around:5000,${anchor.latitudeDeg},${anchor.longitudeDeg});out center tags;"
        } else {
            val (tag, value) = OSM_TYPES[category] ?: error("Unsupported nearby category")
            "[out:json][timeout:18];nwr[\"$tag\"=\"$value\"](around:3000,${anchor.latitudeDeg},${anchor.longitudeDeg});out center tags;"
        }
        var lastError: Throwable? = null
        val endpoints = if (overpassEndpoint == OVERPASS_ENDPOINT) OVERPASS_ENDPOINTS else listOf(overpassEndpoint)
        endpoints.forEach { endpoint ->
            try {
                return executeOverpass(endpoint, statement, anchor, category, query)
            } catch (error: Throwable) {
                lastError = error
            }
        }
        throw lastError ?: IllegalStateException("Nearby data providers are unavailable")
    }

    private fun executeOverpass(endpoint: String, statement: String, anchor: NearbyAnchor, category: String, query: String): List<NearbyPlace> {
        val request = Request.Builder().url(endpoint)
            .header("User-Agent", "NavGhost/${BuildConfig.VERSION_NAME} (nearby search)")
            .post(FormBody.Builder().add("data", statement).build()).build()
        client.newCall(request).execute().use { response ->
            if (!response.isSuccessful) error("Nearby network service returned ${response.code}")
            val elements = JSONObject(response.body?.string().orEmpty()).optJSONArray("elements") ?: JSONArray()
            return (0 until elements.length()).mapNotNull { index ->
                val element = elements.optJSONObject(index) ?: return@mapNotNull null
                val center = element.optJSONObject("center")
                val lat = if (element.has("lat")) element.optDouble("lat", Double.NaN) else center?.optDouble("lat", Double.NaN) ?: Double.NaN
                val lon = if (element.has("lon")) element.optDouble("lon", Double.NaN) else center?.optDouble("lon", Double.NaN) ?: Double.NaN
                if (!lat.isFinite() || !lon.isFinite()) return@mapNotNull null
                val tags = element.optJSONObject("tags") ?: JSONObject()
                val name = sequenceOf("name", "brand", "operator").mapNotNull { tags.optString(it).takeIf(String::isNotBlank) }.firstOrNull()
                    ?: return@mapNotNull null
                if (category != SEARCH_ALL_CATEGORY && query.isNotBlank() && !name.contains(query.trim(), ignoreCase = true)) return@mapNotNull null
                val resolvedCategory = if (category == SEARCH_ALL_CATEGORY) nearbyCategory(tags) else category.replace('_', ' ')
                NearbyPlace(name, resolvedCategory, lat, lon, null, distanceM(anchor.latitudeDeg, anchor.longitudeDeg, lat, lon))
            }
        }
    }

    private fun nearbyCategory(tags: JSONObject): String = sequenceOf("amenity", "shop", "tourism", "leisure", "office")
        .mapNotNull { tags.optString(it).takeIf(String::isNotBlank) }
        .firstOrNull()?.replace('_', ' ') ?: "place"

    companion object {
        private val JSON = "application/json; charset=utf-8".toMediaType()
        private const val CACHE_MS = 120_000L
        private const val MAX_RESULTS = 12
        const val SEARCH_ALL_CATEGORY = "__name_search__"
        private const val OVERPASS_ENDPOINT = "https://overpass-api.de/api/interpreter"
        private val OVERPASS_ENDPOINTS = listOf(
            OVERPASS_ENDPOINT,
            "https://overpass.kumi.systems/api/interpreter",
        )
        private val OSM_TYPES = mapOf(
            "gas_station" to ("amenity" to "fuel"), "parking" to ("amenity" to "parking"),
            "hospital" to ("amenity" to "hospital"), "atm" to ("amenity" to "atm"),
            "car_repair" to ("shop" to "car_repair"),
            "electric_vehicle_charging_station" to ("amenity" to "charging_station"),
            "pharmacy" to ("amenity" to "pharmacy"), "police" to ("amenity" to "police"),
            "restaurant" to ("amenity" to "restaurant"),
        )
        fun distanceM(aLat: Double, aLon: Double, bLat: Double, bLon: Double): Double = TripMetricsAccumulator.haversineM(aLat, aLon, bLat, bLon)
    }
}

data class AndroidApiIdentity(val packageName: String, val certificateSha1: String?) {
    companion object {
        @Suppress("DEPRECATION")
        fun from(context: Context): AndroidApiIdentity {
            val signatures = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
                context.packageManager.getPackageInfo(context.packageName, PackageManager.GET_SIGNING_CERTIFICATES)
                    .signingInfo?.apkContentsSigners
            } else context.packageManager.getPackageInfo(context.packageName, PackageManager.GET_SIGNATURES).signatures
            val sha1 = signatures?.firstOrNull()?.toByteArray()?.let { bytes ->
                MessageDigest.getInstance("SHA-1").digest(bytes).joinToString("") { "%02X".format(Locale.US, it.toInt() and 0xff) }
            }
            return AndroidApiIdentity(context.packageName, sha1)
        }
    }
}
