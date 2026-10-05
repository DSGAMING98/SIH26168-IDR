package org.sih26168.idrlogger.product

import android.util.Log
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.HttpUrl.Companion.toHttpUrlOrNull
import org.json.JSONArray
import org.json.JSONObject

enum class GeoMeshConnectionState { CONFIGURATION_REQUIRED, LOADING, CONNECTED, NO_HAZARD_ZONES, BACKEND_UNAVAILABLE, REQUEST_FAILED }
data class GeoMeshSyncResult(val state: GeoMeshConnectionState, val uploaded: Int = 0, val downloaded: Int = 0, val message: String)

/** Synchronous transport called only by GeoMeshSyncManager's private executor. */
class GeoMeshApiClient(
    baseUrl: String,
    private val client: OkHttpClient = OkHttpClient.Builder().connectTimeout(4, TimeUnit.SECONDS)
        .readTimeout(8, TimeUnit.SECONDS).writeTimeout(8, TimeUnit.SECONDS).callTimeout(10, TimeUnit.SECONDS).build(),
) {
    private val root = baseUrl.trim().trimEnd('/').toHttpUrlOrNull()
    val configured get() = root != null

    fun create(zone: GeoFenceEntity): GeoFenceEntity {
        val json = JSONObject().apply {
            put("client_id", zone.id); put("latitude", zone.latitude); put("longitude", zone.longitude)
            put("radius_m", zone.radiusMeters); put("category", zone.category); put("description", zone.description)
            put("expires_at_ms", zone.expiresAt)
        }
        return parseZone(execute("POST", "/api/geomesh/geofences", json))
    }

    fun vote(zoneId: String, action: String): GeoFenceEntity {
        val path: String; val body: JSONObject?
        if (action == "DENY") { path = "/api/geomesh/geofences/$zoneId/denial"; body = null }
        else { path = "/api/geomesh/geofences/$zoneId/confirmation"; body = JSONObject().put("vote", if (action == "CONFIRM") "STILL_PRESENT" else "NOT_SURE") }
        return parseZone(execute("POST", path, body))
    }

    fun nearby(anchor: NearbyAnchor, spanDegrees: Double = 0.06): List<GeoFenceEntity> {
        val url = requireRoot().newBuilder().addPathSegments("api/geomesh/geofences")
            .addQueryParameter("min_lat", (anchor.latitudeDeg - spanDegrees).toString())
            .addQueryParameter("max_lat", (anchor.latitudeDeg + spanDegrees).toString())
            .addQueryParameter("min_lon", (anchor.longitudeDeg - spanDegrees).toString())
            .addQueryParameter("max_lon", (anchor.longitudeDeg + spanDegrees).toString()).build()
        Log.d(TAG, "GeoMesh request started GET ${url.encodedPath}")
        client.newCall(Request.Builder().url(url).get().build()).execute().use { response ->
            Log.d(TAG, "GeoMesh HTTP ${response.code}")
            if (!response.isSuccessful) error("GeoMesh HTTP ${response.code}")
            val array = JSONObject(response.body?.string().orEmpty()).optJSONArray("geofences") ?: JSONArray()
            return (0 until array.length()).mapNotNull { array.optJSONObject(it)?.let(::parseZone) }
        }
    }

    private fun execute(method: String, path: String, json: JSONObject?): JSONObject {
        val url = requireRoot().newBuilder().addPathSegments(path.trimStart('/')).build()
        Log.d(TAG, "GeoMesh request started $method ${url.encodedPath}")
        val body = (json?.toString() ?: "").toRequestBody(JSON)
        client.newCall(Request.Builder().url(url).post(body).build()).execute().use { response ->
            Log.d(TAG, "GeoMesh HTTP ${response.code}")
            if (!response.isSuccessful) error("GeoMesh HTTP ${response.code}")
            return JSONObject(response.body?.string().orEmpty())
        }
    }

    private fun requireRoot() = root ?: error("GeoMesh backend is not configured")
    private fun parseZone(json: JSONObject) = GeoFenceEntity().apply {
        id = json.getString("id"); latitude = json.getDouble("latitude"); longitude = json.getDouble("longitude")
        radiusMeters = json.getDouble("radius_m"); category = json.getString("category"); description = json.getString("description")
        confidence = json.optInt("confidence", 45); createdAt = json.getLong("created_at_ms"); expiresAt = json.getLong("expires_at_ms")
        lastVerifiedAt = json.optLong("last_verified_at_ms").takeIf { !json.isNull("last_verified_at_ms") }
        verificationCount = json.optInt("confirmations"); denialCount = json.optInt("denials")
        syncState = "SYNCED"; source = "COMMUNITY"
    }

    companion object { private const val TAG = "NavGhostGeoMesh"; private val JSON = "application/json; charset=utf-8".toMediaType() }
}

/** Bounded one-shot sync. It never runs on the localization thread and never retries indefinitely. */
class GeoMeshSyncManager(private val dao: GeoMeshDao, private val api: GeoMeshApiClient) {
    private val running = AtomicBoolean(false)
    fun sync(anchor: NearbyAnchor): GeoMeshSyncResult {
        if (!api.configured) return GeoMeshSyncResult(GeoMeshConnectionState.CONFIGURATION_REQUIRED, message = "Backend configuration required; local GeoMesh remains active.")
        if (!running.compareAndSet(false, true)) return GeoMeshSyncResult(GeoMeshConnectionState.LOADING, message = "GeoMesh sync already running.")
        return try {
            var uploaded = 0
            dao.pending().forEach { pending ->
                val zone = dao.byId(pending.geofenceId) ?: return@forEach
                try {
                    val remote = if (pending.action == "CREATE") api.create(zone) else api.vote(zone.id, pending.action)
                    zone.confidence = remote.confidence; zone.verificationCount = remote.verificationCount; zone.denialCount = remote.denialCount
                    zone.lastVerifiedAt = remote.lastVerifiedAt; zone.syncState = "SYNCED"; dao.update(zone)
                    dao.removePending(pending.id); uploaded++
                } catch (error: Exception) {
                    Log.w("NavGhostGeoMesh", "GeoMesh upload deferred: ${error.message}")
                }
            }
            val downloaded = api.nearby(anchor)
            downloaded.forEach(dao::upsert)
            GeoMeshSyncResult(if (downloaded.isEmpty()) GeoMeshConnectionState.NO_HAZARD_ZONES else GeoMeshConnectionState.CONNECTED,
                uploaded, downloaded.size, if (downloaded.isEmpty()) "Connected • no active zones nearby" else "Connected • ${downloaded.size} nearby zones")
        } catch (error: Exception) {
            Log.w("NavGhostGeoMesh", "GeoMesh backend unavailable: ${error.message}")
            GeoMeshSyncResult(GeoMeshConnectionState.BACKEND_UNAVAILABLE, message = "Backend unavailable • local cache remains active")
        } finally { running.set(false) }
    }
}
