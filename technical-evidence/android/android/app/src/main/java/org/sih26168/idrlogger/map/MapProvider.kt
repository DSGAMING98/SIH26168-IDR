package org.sih26168.idrlogger.map

import org.sih26168.idrlogger.engine.NavigationSnapshot

/**
 * Visual-context boundary. Providers can describe a background but cannot return location.
 * The only marker position exposed to UI is copied from [NavigationSnapshot].
 */
interface MapProvider {
    val id: String
    fun presentation(): MapPresentation
}

enum class MapAvailability { LOCAL_READY, ONLINE_READY, INITIALIZING, NETWORK_UNAVAILABLE }

data class MapPresentation(
    val providerId: String,
    val availability: MapAvailability,
    val primaryLabel: String,
    val detailLabel: String,
    val attribution: String? = null,
)

data class EngineMarker(
    val eastM: Double,
    val northM: Double,
    val latitudeDeg: Double?,
    val longitudeDeg: Double?,
    val headingDeg: Double,
)

/** There is intentionally no MapProvider argument: a visual provider cannot inject position. */
object EngineMarkerPolicy {
    fun from(snapshot: NavigationSnapshot): EngineMarker = snapshot.state.let {
        EngineMarker(it.eastM, it.northM, it.latitudeDeg, it.longitudeDeg, it.headingDeg)
    }
}

/** Guaranteed, credential-free fallback used by every build. */
class LocalEnuMapProvider : MapProvider {
    override val id: String = "local_enu"
    override fun presentation() = MapPresentation(
        providerId = id,
        availability = MapAvailability.LOCAL_READY,
        primaryLabel = "LOCAL ENU • OFFLINE",
        detailLabel = "MAP OFFLINE • LOCAL VIEW",
    )
}

/** Configuration description only; the Android map view owns rendering and has no engine input API. */
class GoogleMapsProvider(
    private val configured: Boolean,
    private val servicesAvailable: Boolean,
) : MapProvider {
    override val id: String = "google_maps"
    override fun presentation(): MapPresentation = when {
        !configured -> LocalEnuMapProvider().presentation()
        !servicesAvailable -> MapPresentation(id, MapAvailability.NETWORK_UNAVAILABLE, "LOCAL MAP", "MAP OFFLINE • NAVIGATION ACTIVE")
        else -> MapPresentation(id, MapAvailability.INITIALIZING, "MAP CONNECTING", "NAVIGATION ACTIVE", "Google")
    }
}

object MapProviderRegistry {
    fun competitionDefault(mapsConfigured: Boolean = false, servicesAvailable: Boolean = false): MapProvider =
        if (mapsConfigured) GoogleMapsProvider(true, servicesAvailable) else LocalEnuMapProvider()
}
