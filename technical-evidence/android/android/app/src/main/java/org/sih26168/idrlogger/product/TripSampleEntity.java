package org.sih26168.idrlogger.product;

import androidx.room.Entity;
import androidx.room.ForeignKey;
import androidx.room.Index;
import androidx.room.PrimaryKey;

/** Downsampled product trajectory (nominally 1 Hz), not the raw 50 Hz sensor log. */
@Entity(
    tableName = "trip_samples",
    foreignKeys = @ForeignKey(entity = TripEntity.class, parentColumns = "id", childColumns = "tripId", onDelete = ForeignKey.CASCADE),
    indices = {@Index("tripId")}
)
public class TripSampleEntity {
    @PrimaryKey(autoGenerate = true) public long id;
    public long tripId;
    public long wallTimeMs;
    public double elapsedSeconds;
    public double latitudeDeg;
    public double longitudeDeg;
    public double speedMps;
    public double headingDeg;
    public Double uncertaintyM;
    public String localizationMode;
}
