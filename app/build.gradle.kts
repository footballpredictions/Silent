import java.util.Properties

plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
    alias(libs.plugins.kotlin.compose)
    alias(libs.plugins.ksp)
    id("com.google.dagger.hilt.android") version "2.53"
}

val keystorePropertiesFile = file("../keystore/keystore.properties")
val keystoreProperties = Properties().apply {
    if (keystorePropertiesFile.exists()) {
        load(keystorePropertiesFile.inputStream())
    }
}

/** Debug: фиксированный VK-хеш для bootstrap VPN на экране входа. Release — только через -PbootstrapVkHash. */
private val debugBootstrapVkHash = "vP_C4iBk9QZEetqR0a_MqiPJkeOyBEV1B_G6uViHuVU"

android {
    namespace = "com.silent.vpn"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.silent.vpn"
        minSdk = 26
        targetSdk = 35
        versionCode = 144
        versionName = "1.0.144"
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
        ndk {
            abiFilters += listOf("arm64-v8a", "armeabi-v7a")
        }
    }

    signingConfigs {
        if (keystorePropertiesFile.exists()) {
            create("release") {
                storeFile = file("../keystore/${keystoreProperties.getProperty("storeFile")}")
                storePassword = keystoreProperties.getProperty("storePassword")
                keyAlias = keystoreProperties.getProperty("keyAlias")
                keyPassword = keystoreProperties.getProperty("keyPassword")
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
            signingConfigs.findByName("release")?.let { signingConfig = it }
            val releaseHash = (project.findProperty("bootstrapVkHash") as String?)?.trim()?.takeIf { it.isNotEmpty() }
            buildConfigField(
                "String",
                "BOOTSTRAP_VK_HASH",
                "\"${releaseHash ?: debugBootstrapVkHash}\"",
            )
        }
        debug {
            isMinifyEnabled = false
            applicationIdSuffix = ".debug"
            resValue("string", "app_name", "Silent VPN (debug)")
            buildConfigField("String", "BOOTSTRAP_VK_HASH", "\"$debugBootstrapVkHash\"")
        }
    }
    lint {
        checkReleaseBuilds = false
        abortOnError = false
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
    buildFeatures { compose = true; buildConfig = true }
    packaging {
        jniLibs { useLegacyPackaging = true }
    }
    sourceSets {
        getByName("main") {
            jniLibs.srcDirs("src/main/jniLibs")
        }
    }
}

dependencies {
    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.lifecycle.runtime.ktx)
    implementation(libs.androidx.activity.compose)
    implementation(platform(libs.androidx.compose.bom))
    implementation(libs.androidx.ui)
    implementation(libs.androidx.ui.graphics)
    implementation(libs.androidx.ui.tooling.preview)
    implementation(libs.androidx.material3)
    implementation(libs.androidx.navigation.compose)
    implementation(libs.androidx.datastore.preferences)

    // Network
    implementation(libs.retrofit)
    implementation(libs.retrofit.gson)
    implementation(libs.okhttp.logging)

    // DI
    implementation(libs.hilt.android)
    ksp(libs.hilt.compiler)
    implementation(libs.hilt.navigation.compose)

    // Coroutines
    implementation(libs.kotlinx.coroutines.android)

    // Security (encrypted storage)
    implementation(libs.security.crypto)

    // WireGuard
    implementation(libs.wireguard.android)

    // AppCompat (for theme)
    implementation(libs.appcompat)

    // Extended icons
    implementation(libs.androidx.material.icons.extended)

    // ViewModel for Compose
    implementation(libs.androidx.lifecycle.viewmodel.compose)

    // Google Password Manager / Credential Manager
    implementation("androidx.credentials:credentials:1.5.0")
    implementation("androidx.credentials:credentials-play-services-auth:1.5.0")

    // Unit tests
    testImplementation(libs.junit)
    testImplementation(libs.kotlin.test)
    testImplementation(libs.kotlinx.coroutines.test)
}

gradle.taskGraph.whenReady {
    val releaseTasks = setOf("assembleRelease", "bundleRelease", "installRelease", "packageRelease")
    val buildingRelease = allTasks.any { task ->
        task.project == project && releaseTasks.any { task.name.equals(it, ignoreCase = true) }
    }
    if (buildingRelease) {
        val releaseHash = (project.findProperty("bootstrapVkHash") as String?)?.trim()?.takeIf { it.isNotEmpty() }
        if (releaseHash == null) {
            throw GradleException(
                """
                Release-сборка Android: нужен актуальный VK bootstrap-хеш.
                  ./gradlew assembleRelease -PbootstrapVkHash=XXXX
                Ссылка vk.com/call/join/… — спросите у владельца проекта перед каждым релизом.
                """.trimIndent(),
            )
        }
    }
}
