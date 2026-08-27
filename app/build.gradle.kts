import java.io.File
import java.io.FileInputStream
import java.security.KeyStore
import java.security.MessageDigest
import java.security.cert.X509Certificate
import java.util.Properties
import java.util.zip.ZipFile

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

fun sha256FileHex(f: File): String {
    if (!f.isFile) return ""
    val md = MessageDigest.getInstance("SHA-256")
    FileInputStream(f).use { input ->
        val buf = ByteArray(8192)
        while (true) {
            val n = input.read(buf)
            if (n <= 0) break
            md.update(buf, 0, n)
        }
    }
    return md.digest().joinToString("") { b -> "%02x".format(b) }
}

/** SHA-256 DER сертификата release-keystore (для pin в AppIntegrity). Пусто если keystore нет. */
fun releaseCertSha256Hex(): String {
    if (!keystorePropertiesFile.exists()) return ""
    val storeFileName = keystoreProperties.getProperty("storeFile") ?: return ""
    val storeFile = file("../keystore/$storeFileName")
    if (!storeFile.isFile) return ""
    val storePass = (keystoreProperties.getProperty("storePassword") ?: "").toCharArray()
    val keyAlias = keystoreProperties.getProperty("keyAlias") ?: return ""
    return try {
        val ks = KeyStore.getInstance(KeyStore.getDefaultType())
        FileInputStream(storeFile).use { ks.load(it, storePass) }
        val cert = ks.getCertificate(keyAlias) as? X509Certificate ?: return ""
        MessageDigest.getInstance("SHA-256").digest(cert.encoded)
            .joinToString("") { b -> "%02x".format(b) }
    } catch (_: Exception) {
        ""
    }
}

val libclientShaArm64 = sha256FileHex(file("src/main/jniLibs/arm64-v8a/libclient.so"))
val libclientShaArm32 = sha256FileHex(file("src/main/jniLibs/armeabi-v7a/libclient.so"))
val libclientShaX64 = sha256FileHex(file("src/main/jniLibs/x86_64/libclient.so"))
val libclientShaX86 = sha256FileHex(file("src/main/jniLibs/x86/libclient.so"))
val releaseCertSha = releaseCertSha256Hex()
val releaseAbis = listOf("arm64-v8a", "armeabi-v7a", "x86_64", "x86")
val forbiddenReleaseLibs = setOf("libolcrtc.so", "libolcrtc2.so", "libhev-socks5-tunnel.so")

android {
    namespace = "com.silent.vpn"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.silent.vpn"
        minSdk = 24
        targetSdk = 35
        versionCode = 163
        versionName = "1.0.163"
        testInstrumentationRunner = "com.silent.vpn.HiltTestRunner"
        // Не сбрасывать данные приложения при каждом прогоне — сохраняется логин/VPN-разрешение.
        testInstrumentationRunnerArguments["clearPackageData"] = "false"
        ndk {
            abiFilters += listOf("arm64-v8a", "armeabi-v7a", "x86_64", "x86")
        }
    }

    signingConfigs {
        if (keystorePropertiesFile.exists()) {
            create("release") {
                storeFile = file("../keystore/${keystoreProperties.getProperty("storeFile")}")
                storePassword = keystoreProperties.getProperty("storePassword")
                keyAlias = keystoreProperties.getProperty("keyAlias")
                keyPassword = keystoreProperties.getProperty("keyPassword")
                // Максимальная совместимость sideload на TV/приставках.
                enableV1Signing = true
                enableV2Signing = true
                enableV3Signing = true
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
            // Integrity pins (AppIntegrity) — хеши из jniLibs + отпечаток release-сертификата
            buildConfigField("String", "RELEASE_CERT_SHA256", "\"$releaseCertSha\"")
            buildConfigField("String", "LIBCLIENT_SHA256_ARM64", "\"$libclientShaArm64\"")
            buildConfigField("String", "LIBCLIENT_SHA256_ARM32", "\"$libclientShaArm32\"")
            buildConfigField("String", "LIBCLIENT_SHA256_X86_64", "\"$libclientShaX64\"")
            buildConfigField("String", "LIBCLIENT_SHA256_X86", "\"$libclientShaX86\"")
        }
        debug {
            isMinifyEnabled = false
            applicationIdSuffix = ".debug"
            resValue("string", "app_name", "Silent VPN (debug)")
            buildConfigField("String", "BOOTSTRAP_VK_HASH", "\"$debugBootstrapVkHash\"")
            // Debug: пустые pins → AppIntegrity пропускает проверки
            buildConfigField("String", "RELEASE_CERT_SHA256", "\"\"")
            buildConfigField("String", "LIBCLIENT_SHA256_ARM64", "\"\"")
            buildConfigField("String", "LIBCLIENT_SHA256_ARM32", "\"\"")
            buildConfigField("String", "LIBCLIENT_SHA256_X86_64", "\"\"")
            buildConfigField("String", "LIBCLIENT_SHA256_X86", "\"\"")
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
        jniLibs {
            useLegacyPackaging = true
            // AppIntegrity pins SHA-256 of jniLibs/libclient.so. AGP stripReleaseDebugSymbols
            // rewrites the ELF even when size is unchanged → runtime hash mismatch and
            // «VPN-модуль изменён или повреждён». Keep symbols so packaged == pinned.
            keepDebugSymbols += listOf("**/libclient.so")
            // olcrtc снят: мёртвые .so (~190 МБ) ломали OTA на TV («приложение не установлено»).
            excludes += setOf(
                "**/libolcrtc.so",
                "**/libolcrtc2.so",
                "**/libhev-socks5-tunnel.so",
            )
        }
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
    testImplementation(libs.okhttp.mockwebserver)

    // Instrumented tests (эмулятор или телефон по USB)
    androidTestImplementation(libs.androidx.test.ext.junit)
    androidTestImplementation(libs.androidx.test.runner)
    androidTestImplementation(libs.androidx.test.rules)
    androidTestImplementation(libs.kotlinx.coroutines.test)
    androidTestImplementation(libs.okhttp.mockwebserver)
    androidTestImplementation("com.google.dagger:hilt-android-testing:2.53")
    kspAndroidTest(libs.hilt.compiler)
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
        val missingLibclientAbis = releaseAbis.filter { abi ->
            !file("src/main/jniLibs/$abi/libclient.so").isFile
        }
        if (missingLibclientAbis.isNotEmpty()) {
            throw GradleException(
                """
                Release-сборка Android: отсутствует libclient.so для ABI: ${missingLibclientAbis.joinToString(", ")}.
                Нельзя выпускать OTA без полного набора ABI (arm64/armv7/x86/x86_64), иначе часть TV/приставок не установит APK.
                Пересоберите native: app\build_android_go.bat
                """.trimIndent(),
            )
        }
    }
}

tasks.register("verifyReleaseApkNativeLayout") {
    group = "verification"
    description = "Проверяет ABI и forbidden .so в app-release.apk"
    doLast {
        val releaseDir = file("$buildDir/outputs/apk/release")
        val apk = releaseDir
            .listFiles()
            ?.filter { it.isFile && it.extension.equals("apk", ignoreCase = true) }
            ?.maxByOrNull { it.lastModified() }
            ?: throw GradleException("Не найден release APK в: ${releaseDir.path}")
        if (!apk.isFile) {
            throw GradleException("Не найден APK для проверки: ${apk.path}")
        }
        val nativeEntries = mutableSetOf<String>()
        ZipFile(apk).use { zip ->
            val en = zip.entries()
            while (en.hasMoreElements()) {
                val name = en.nextElement().name
                if (name.startsWith("lib/") && name.endsWith(".so")) {
                    nativeEntries += name
                }
            }
        }
        val missingLibclientInApk = releaseAbis.filter { abi ->
            "lib/$abi/libclient.so" !in nativeEntries
        }
        if (missingLibclientInApk.isNotEmpty()) {
            throw GradleException(
                "APK не содержит libclient.so для ABI: ${missingLibclientInApk.joinToString(", ")}",
            )
        }
        val forbiddenInApk = nativeEntries.filter { entry ->
            forbiddenReleaseLibs.any { lib -> entry.endsWith("/$lib") }
        }
        if (forbiddenInApk.isNotEmpty()) {
            throw GradleException(
                "В release APK попали запрещённые legacy libs: ${forbiddenInApk.joinToString(", ")}",
            )
        }
        println("verifyReleaseApkNativeLayout: OK (${nativeEntries.size} native libs)")
    }
}

tasks.matching { it.name == "assembleRelease" }.configureEach {
    finalizedBy("verifyReleaseApkNativeLayout")
}
