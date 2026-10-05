package org.sih26168.idrlogger.product;

import androidx.room.Dao;
import androidx.room.Delete;
import androidx.room.Insert;
import androidx.room.Query;
import androidx.room.Update;
import java.util.List;

@Dao
public interface TripDao {
    @Insert long insertTrip(TripEntity trip);
    @Insert long insertSample(TripSampleEntity sample);
    @Update int updateTrip(TripEntity trip);
    @Delete int deleteTrip(TripEntity trip);
    @Query("SELECT * FROM trips ORDER BY startWallTimeMs DESC") List<TripEntity> allTrips();
    @Query("SELECT * FROM trips WHERE id = :id LIMIT 1") TripEntity trip(long id);
    @Query("SELECT * FROM trip_samples WHERE tripId = :tripId ORDER BY elapsedSeconds ASC") List<TripSampleEntity> samples(long tripId);
    @Query("UPDATE trips SET status = 'INTERRUPTED', endWallTimeMs = startWallTimeMs + CAST(durationSeconds * 1000 AS INTEGER) WHERE status = 'RUNNING'") int markAbandonedTripsInterrupted();
}
