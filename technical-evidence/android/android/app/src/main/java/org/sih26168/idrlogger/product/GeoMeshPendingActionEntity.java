package org.sih26168.idrlogger.product;

import androidx.annotation.NonNull;
import androidx.room.Entity;
import androidx.room.PrimaryKey;

/** Durable upload queue. Cache cleanup must never remove these rows. */
@Entity(tableName = "geomesh_pending_actions")
public class GeoMeshPendingActionEntity {
    @PrimaryKey(autoGenerate = true) public long id;
    @NonNull public String geofenceId = "";
    @NonNull public String action = "CREATE";
    public long createdAt;
    public int attempts;
}
