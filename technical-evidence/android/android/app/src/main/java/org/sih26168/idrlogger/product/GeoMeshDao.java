package org.sih26168.idrlogger.product;

import androidx.room.Dao;
import androidx.room.Insert;
import androidx.room.OnConflictStrategy;
import androidx.room.Query;
import androidx.room.Update;
import java.util.List;

@Dao
public interface GeoMeshDao {
    @Insert(onConflict = OnConflictStrategy.REPLACE) void upsert(GeoFenceEntity zone);
    @Update int update(GeoFenceEntity zone);
    @Query("SELECT * FROM geomesh_zones WHERE expiresAt > :now ORDER BY confidence DESC, createdAt DESC") List<GeoFenceEntity> active(long now);
    @Query("SELECT * FROM geomesh_zones WHERE id = :id LIMIT 1") GeoFenceEntity byId(String id);
    @Insert long enqueue(GeoMeshPendingActionEntity action);
    @Query("SELECT * FROM geomesh_pending_actions ORDER BY createdAt ASC") List<GeoMeshPendingActionEntity> pending();
    @Query("DELETE FROM geomesh_pending_actions WHERE id = :id") int removePending(long id);
    @Query("SELECT COUNT(*) FROM geomesh_pending_actions") int pendingCount();
    @Query("DELETE FROM geomesh_zones WHERE id = :id") int deleteZone(String id);
}
