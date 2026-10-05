package org.sih26168.idrlogger.product;

import android.content.Context;
import androidx.room.Database;
import androidx.room.Room;
import androidx.room.RoomDatabase;
import androidx.room.migration.Migration;
import androidx.sqlite.db.SupportSQLiteDatabase;

@Database(entities = {TripEntity.class, TripSampleEntity.class, GeoFenceEntity.class, GeoMeshPendingActionEntity.class}, version = 2, exportSchema = true)
public abstract class NavGhostDatabase extends RoomDatabase {
    public abstract TripDao tripDao();
    public abstract GeoMeshDao geoMeshDao();
    private static volatile NavGhostDatabase instance;

    public static NavGhostDatabase get(Context context) {
        if (instance == null) synchronized (NavGhostDatabase.class) {
            if (instance == null) instance = Room.databaseBuilder(
                context.getApplicationContext(), NavGhostDatabase.class, "navghost-product.db"
            ).addMigrations(MIGRATION_1_2).build();
        }
        return instance;
    }

    static final Migration MIGRATION_1_2 = new Migration(1, 2) {
        @Override public void migrate(SupportSQLiteDatabase db) {
            db.execSQL("CREATE TABLE IF NOT EXISTS `geomesh_zones` (`id` TEXT NOT NULL, `latitude` REAL NOT NULL, `longitude` REAL NOT NULL, `radiusMeters` REAL NOT NULL, `category` TEXT NOT NULL, `description` TEXT NOT NULL, `confidence` INTEGER NOT NULL, `createdAt` INTEGER NOT NULL, `expiresAt` INTEGER NOT NULL, `lastVerifiedAt` INTEGER, `verificationCount` INTEGER NOT NULL, `denialCount` INTEGER NOT NULL, `syncState` TEXT NOT NULL, `source` TEXT NOT NULL, PRIMARY KEY(`id`))");
            db.execSQL("CREATE TABLE IF NOT EXISTS `geomesh_pending_actions` (`id` INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL, `geofenceId` TEXT NOT NULL, `action` TEXT NOT NULL, `createdAt` INTEGER NOT NULL, `attempts` INTEGER NOT NULL)");
        }
    };
}
