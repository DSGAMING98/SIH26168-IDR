package org.sih26168.idrlogger.ui

import android.content.Context
import java.io.File

data class AppStorageSummary(val recordingsBytes: Long, val temporaryBytes: Long)

/** Reports and clears NavGhost-owned cache only; recordings and external map caches are never deleted. */
object AppStorageAudit {
    fun inspect(context: Context): AppStorageSummary = AppStorageSummary(
        recordingsBytes = sizeOf(File(context.filesDir, "recordings")),
        temporaryBytes = sizeOf(temporaryRoot(context)),
    )

    fun clearTemporaryCache(context: Context): Long {
        val root = temporaryRoot(context)
        val before = sizeOf(root)
        root.listFiles()?.forEach { deleteOwned(it, root) }
        return before - sizeOf(root)
    }

    private fun temporaryRoot(context: Context) = File(context.cacheDir, "navghost")

    private fun sizeOf(file: File): Long = when {
        !file.exists() -> 0L
        file.isFile -> file.length()
        else -> file.listFiles()?.sumOf(::sizeOf) ?: 0L
    }

    private fun deleteOwned(file: File, root: File) {
        val rootPath = root.canonicalFile.toPath()
        val target = file.canonicalFile.toPath()
        check(target.startsWith(rootPath) && target != rootPath)
        if (file.isDirectory) file.listFiles()?.forEach { deleteOwned(it, root) }
        file.delete()
    }
}
