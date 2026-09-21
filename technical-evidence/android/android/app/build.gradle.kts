import java.util.Properties

plugins {
    id("com.android.application")
}

val localProperties = Properties().apply {
    val file = rootProject.file("local.properties")
    if (file.isFile) file.inputStream().use { load(it) }
}
val mapsApiKey = localProperties.getProperty("MAPS_API_KEY").orEmpty().trim()
val maps3dApiKey = localProperties.getProperty("MAPS3D_API_KEY").orEmpty().trim()
val placesApiKey = localProperties.getProperty("PLACES_API_KEY").orEmpty().trim()
val signingProperties = Properties().apply {
    val file = rootProject.file("signing.properties")
    if (file.isFile) file.inputStream().use { load(it) }
}
val releaseSigningConfigured = listOf("storeFile", "storePassword", "keyAlias", "keyPassword")
    .all { !signingProperties.getProperty(it).isNullOrBlank() }
require(maps3dApiKey.isNotEmpty()) {
    "MAPS3D_API_KEY is required in android/local.properties for the Google Maps 3D build."
}
// Explicit build-time trusted LAN host; generated resources and local properties are untracked.
// No global cleartext exception and no personal network address committed to source.
val telemetryLanHost = providers.gradleProperty("NAVGHOST_LAN_HOST").orElse("").get().trim()
val geomeshPort = providers.gradleProperty("NAVGHOST_GEOMESH_PORT").orElse("8000").get().toIntOrNull()
    ?: error("NAVGHOST_GEOMESH_PORT must be an integer")
require(geomeshPort in 1..65535) { "NAVGHOST_GEOMESH_PORT must be in 1..65535" }
if (telemetryLanHost.isNotEmpty()) {
    val octets = telemetryLanHost.split('.').map { it.toIntOrNull() ?: -1 }
    require(octets.size == 4 && octets.all { it in 0..255 } &&
        (telemetryLanHost == "127.0.0.1" || octets[0] == 10 || (octets[0] == 192 && octets[1] == 168) ||
            (octets[0] == 172 && octets[1] in 16..31) || (octets[0] == 169 && octets[1] == 254))) {
        "NAVGHOST_LAN_HOST must be one trusted private IPv4 literal"
    }
}
val telemetryNetworkRes = layout.buildDirectory.dir("generated/telemetryNetwork/res")
val generateTelemetryNetworkSecurity by tasks.registering {
    inputs.property("trustedLanHost", telemetryLanHost)
    outputs.dir(telemetryNetworkRes)
    doLast {
        val file = telemetryNetworkRes.get().file("xml/navghost_network_security.xml").asFile
        file.parentFile.mkdirs()
        val hosts = (listOf("localhost", "127.0.0.1", "10.0.2.2") + listOf(telemetryLanHost).filter { it.isNotEmpty() }).distinct()
        file.writeText("""<?xml version="1.0" encoding="utf-8"?>
<network-security-config>
  <base-config cleartextTrafficPermitted="false" />
  <domain-config cleartextTrafficPermitted="true">
${hosts.joinToString("\n") { "    <domain includeSubdomains=\"false\">$it</domain>" }}
  </domain-config>
</network-security-config>
""")
    }
}
tasks.matching { it.name == "preBuild" }.configureEach { dependsOn(generateTelemetryNetworkSecurity) }

android {
    namespace = "org.sih26168.idrlogger"
    sourceSets.getByName("main").res.srcDir(telemetryNetworkRes.get().asFile)
    compileSdk {
        version = release(36) {
            minorApiLevel = 1
        }
    }

    defaultConfig {
        applicationId = "org.sih26168.idrlogger"
        minSdk = 26
        targetSdk = 36
        versionCode = 41
        versionName = "2.4.0"

        manifestPlaceholders["MAPS_API_KEY"] = mapsApiKey
        manifestPlaceholders["MAPS3D_API_KEY"] = maps3dApiKey
        buildConfigField("boolean", "MAPS_CONFIGURED", mapsApiKey.isNotEmpty().toString())
        buildConfigField("boolean", "MAPS3D_CONFIGURED", maps3dApiKey.isNotEmpty().toString())
        buildConfigField("String", "PLACES_API_KEY", "\"${placesApiKey.replace("\\", "\\\\").replace("\"", "\\\"")}\"")
        buildConfigField("boolean", "PLACES_CONFIGURED", placesApiKey.isNotEmpty().toString())
        val geoMeshUrl = telemetryLanHost.takeIf { it.isNotEmpty() }?.let { "http://$it:$geomeshPort" }.orEmpty()
        buildConfigField("String", "GEOMESH_BASE_URL", "\"$geoMeshUrl\"")
        buildConfigField("boolean", "GEOMESH_CONFIGURED", geoMeshUrl.isNotEmpty().toString())

        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
    }

    buildFeatures {
        buildConfig = true
    }

    signingConfigs {
        create("release") {
            if (releaseSigningConfigured) {
                storeFile = rootProject.file(signingProperties.getProperty("storeFile"))
                storePassword = signingProperties.getProperty("storePassword")
                keyAlias = signingProperties.getProperty("keyAlias")
                keyPassword = signingProperties.getProperty("keyPassword")
                enableV1Signing = true
                enableV2Signing = true
                enableV3Signing = true
                enableV4Signing = true
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            if (releaseSigningConfigured) signingConfig = signingConfigs.getByName("release")
        }
    }

    testOptions {
        unitTests.isReturnDefaultValues = true
    }
}

tasks.matching { it.name == "assembleRelease" || it.name == "bundleRelease" }.configureEach {
    doFirst {
        require(releaseSigningConfigured) {
            "Release signing is not configured. Copy signing.properties.example to the ignored signing.properties file and provide the persistent NavGhost release key."
        }
    }
}

dependencies {
    implementation("com.google.android.gms:play-services-maps:20.0.0")
    implementation("com.google.android.gms:play-services-maps3d:0.2.2")
    implementation("org.maplibre.gl:android-sdk:13.4.1")
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
    implementation("androidx.room:room-runtime:2.7.2")
    annotationProcessor("androidx.room:room-compiler:2.7.2")
    implementation("androidx.datastore:datastore-preferences:1.1.7")
    testImplementation("junit:junit:4.13.2")
    testImplementation("com.squareup.okhttp3:mockwebserver:4.12.0")
    androidTestImplementation("androidx.test:runner:1.7.0")
    androidTestImplementation("androidx.test:core:1.7.0")
    androidTestImplementation("junit:junit:4.13.2")
}
