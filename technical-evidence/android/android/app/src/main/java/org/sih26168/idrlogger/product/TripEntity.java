package org.sih26168.idrlogger.product;

import androidx.annotation.NonNull;
import androidx.room.Entity;
import androidx.room.PrimaryKey;

/** Compact, user-facing trip summary. Raw high-rate sensor data remains in session exports. */
@Entity(tableName = "trips")
public class TripEntity {
    @PrimaryKey(autoGenerate = true) public long id;
    public long startWallTimeMs;
    public Long endWallTimeMs;
    @NonNull public String title = "Trip";
    @NonNull public String status = "RUNNING";
    public String sessionDirectory;
    public Double startLatitudeDeg;
    public Double startLongitudeDeg;
    public Double endLatitudeDeg;
    public Double endLongitudeDeg;
    public double distanceM;
    public double durationSeconds;
    public double averageSpeedMps;
    public double maximumSpeedMps;
    public int gnssLossEvents;
    public double gnssActiveDurationSeconds;
    public double idrDurationSeconds;
    public double longestIdrIntervalSeconds;
    public Double averageUncertaintyM;
    public Double maximumUncertaintyM;
    public String rendererUsed;
    public boolean gruAssistanceUsed;
    public String appVersion;
    public String deviceModel;
}
