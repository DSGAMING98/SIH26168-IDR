package org.sih26168.idrlogger.product

import kotlin.math.max
import org.sih26168.idrlogger.engine.NavigationSnapshot

private const val GEOMESH_HOUR_MS = 3_600_000L
private const val GEOMESH_DAY_MS = 86_400_000L

enum class GeoMeshCategory(val label: String, val defaultLifetimeMs: Long) {
    ROAD_BLOCK("Road block", 4 * GEOMESH_HOUR_MS), ACCIDENT("Accident", 2 * GEOMESH_HOUR_MS), CONSTRUCTION("Construction", 7 * GEOMESH_DAY_MS),
    FLOODING("Flooding", 12 * GEOMESH_HOUR_MS), POTHOLE("Pothole / road damage", 30 * GEOMESH_DAY_MS),
    DANGEROUS_ROAD("Dangerous road", 7 * GEOMESH_DAY_MS), PARKING_RESTRICTION("Parking restriction", GEOMESH_DAY_MS),
    EMERGENCY_ZONE("Emergency zone", 4 * GEOMESH_HOUR_MS), TUNNEL_GNSS_DEGRADED("Tunnel / GNSS degraded", 30 * GEOMESH_DAY_MS),
    CUSTOM_WARNING("Custom warning", GEOMESH_DAY_MS);
}

enum class GeoMeshProximity { OUTSIDE, APPROACHING, ENTERED, INSIDE, EXITED }
data class GeoMeshHit(val zone: GeoFenceEntity, val distanceM: Double, val proximity: GeoMeshProximity)

object GeoMeshConfidence {
    fun score(createdAt: Long, now: Long, confirmations: Int, denials: Int, lastVerifiedAt: Long?): Int {
        val ageHours = ((now - createdAt).coerceAtLeast(0) / GEOMESH_HOUR_MS.toDouble())
        val recent = lastVerifiedAt?.let { now - it <= 6 * GEOMESH_HOUR_MS } == true
        return (45 + confirmations.coerceAtMost(6) * 8 - denials.coerceAtMost(5) * 12 - (ageHours / 24).toInt() * 3 + if (recent) 8 else 0).coerceIn(0, 100)
    }
}

/** Stateful proximity labels are presentation evidence only and cannot mutate localization. */
class GeoMeshEngine {
    private val inside = mutableSetOf<String>()
    fun evaluate(snapshot: NavigationSnapshot, zones: List<GeoFenceEntity>, now: Long): List<GeoMeshHit> {
        val anchor = NearbyQueryFactory.from(snapshot) as? NearbyQueryResult.Ready ?: return emptyList()
        val activeIds = mutableSetOf<String>()
        val hits = zones.filter { it.expiresAt > now }.mapNotNull { zone ->
            val distance = NearbyPlacesClient.distanceM(anchor.anchor.latitudeDeg, anchor.anchor.longitudeDeg, zone.latitude, zone.longitude)
            val isInside = distance <= zone.radiusMeters
            if (isInside) activeIds += zone.id
            val state = when {
                isInside && zone.id !in inside -> GeoMeshProximity.ENTERED
                isInside -> GeoMeshProximity.INSIDE
                !isInside && zone.id in inside -> GeoMeshProximity.EXITED
                distance <= zone.radiusMeters + max(100.0, zone.radiusMeters) -> GeoMeshProximity.APPROACHING
                else -> GeoMeshProximity.OUTSIDE
            }
            if (state == GeoMeshProximity.OUTSIDE) null else GeoMeshHit(zone, distance, state)
        }.sortedBy(GeoMeshHit::distanceM)
        inside.clear(); inside += activeIds
        return hits
    }
}
