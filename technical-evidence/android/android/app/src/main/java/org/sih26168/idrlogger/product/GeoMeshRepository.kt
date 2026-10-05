package org.sih26168.idrlogger.product

import android.content.Context
import java.util.UUID
import java.util.concurrent.Executors
import org.sih26168.idrlogger.engine.NavigationSnapshot
import org.sih26168.idrlogger.BuildConfig

class GeoMeshRepository(context: Context) {
    private val dao = NavGhostDatabase.get(context).geoMeshDao()
    private val executor = Executors.newSingleThreadExecutor()
    private val engine = GeoMeshEngine()
    private val syncManager = GeoMeshSyncManager(dao, GeoMeshApiClient(BuildConfig.GEOMESH_BASE_URL))

    fun create(snapshot: NavigationSnapshot, category: GeoMeshCategory, description: String, radiusM: Double = 75.0,
               now: Long = System.currentTimeMillis(), callback: (Result<GeoFenceEntity>) -> Unit) {
        val anchor = NearbyQueryFactory.from(snapshot) as? NearbyQueryResult.Ready
            ?: return callback(Result.failure(IllegalStateException("Acquire a NavGhost position before creating a zone.")))
        executor.execute { callback(runCatching {
            val zone = GeoFenceEntity().apply {
                id = UUID.randomUUID().toString(); latitude = anchor.anchor.latitudeDeg; longitude = anchor.anchor.longitudeDeg
                radiusMeters = radiusM.coerceIn(20.0, 1000.0); this.category = category.name
                this.description = description.take(160); createdAt = now; expiresAt = now + category.defaultLifetimeMs
                confidence = GeoMeshConfidence.score(createdAt, now, 0, 0, null)
            }
            dao.upsert(zone); dao.enqueue(action(zone.id, "CREATE", now)); zone
        }) }
    }

    fun active(snapshot: NavigationSnapshot, now: Long = System.currentTimeMillis(), callback: (List<GeoMeshHit>, Int) -> Unit) = executor.execute {
        callback(engine.evaluate(snapshot, dao.active(now), now), dao.pendingCount())
    }

    fun allActive(now: Long = System.currentTimeMillis(), callback: (List<GeoFenceEntity>, Int) -> Unit) = executor.execute {
        callback(dao.active(now), dao.pendingCount())
    }

    fun sync(snapshot: NavigationSnapshot, callback: (GeoMeshSyncResult) -> Unit) {
        val anchor = NearbyQueryFactory.from(snapshot) as? NearbyQueryResult.Ready
            ?: return callback(GeoMeshSyncResult(GeoMeshConnectionState.REQUEST_FAILED, message = "Acquire a NavGhost position before syncing."))
        executor.execute { callback(syncManager.sync(anchor.anchor)) }
    }

    fun verify(id: String, present: Boolean?, now: Long = System.currentTimeMillis(), callback: (GeoFenceEntity?) -> Unit = {}) = executor.execute {
        val zone = dao.byId(id) ?: return@execute callback(null)
        if (present == true) { zone.verificationCount++; zone.lastVerifiedAt = now }
        if (present == false) zone.denialCount++
        zone.confidence = GeoMeshConfidence.score(zone.createdAt, now, zone.verificationCount, zone.denialCount, zone.lastVerifiedAt)
        zone.syncState = "PENDING_SYNC"; dao.update(zone)
        dao.enqueue(action(zone.id, when (present) { true -> "CONFIRM"; false -> "DENY"; null -> "NOT_SURE" }, now)); callback(zone)
    }

    private fun action(id: String, type: String, now: Long) = GeoMeshPendingActionEntity().apply {
        geofenceId = id; action = type; createdAt = now
    }
}
