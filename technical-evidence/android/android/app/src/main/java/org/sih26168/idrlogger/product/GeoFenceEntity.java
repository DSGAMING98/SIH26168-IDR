package org.sih26168.idrlogger.product;

import androidx.annotation.NonNull;
import androidx.room.Entity;
import androidx.room.PrimaryKey;

/** Offline-first community zone. It is a consumer of NavGhost estimates, never a positioning input. */
@Entity(tableName = "geomesh_zones")
public class GeoFenceEntity {
    @PrimaryKey @NonNull public String id = "";
    public double latitude;
    public double longitude;
    public double radiusMeters;
    @NonNull public String category = "CUSTOM_WARNING";
    @NonNull public String description = "";
    public int confidence;
    public long createdAt;
    public long expiresAt;
    public Long lastVerifiedAt;
    public int verificationCount;
    public int denialCount;
    @NonNull public String syncState = "PENDING_SYNC";
    @NonNull public String source = "LOCAL_USER";
}
