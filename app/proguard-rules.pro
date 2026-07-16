-dontwarn com.google.errorprone.annotations.**
-dontwarn javax.annotation.**
-dontwarn org.codehaus.mojo.animal_sniffer.*
-dontwarn com.google.crypto.tink.**

# Hilt / DI
-keep class dagger.hilt.** { *; }
-keep class javax.inject.** { *; }
-keep @dagger.hilt.android.lifecycle.HiltViewModel class * { *; }
-keep class * extends androidx.lifecycle.ViewModel { *; }
-keepattributes *Annotation*
-keepattributes Signature
-keepattributes Exceptions

# Entry points / services / VPN core (не обфусцировать — reflection, Manifest, ProcessBuilder)
-keep class com.silent.vpn.SilentApp { *; }
-keep class com.silent.vpn.MainActivity { *; }
-keep class com.silent.vpn.MainActivityRoot { *; }
-keep class com.silent.vpn.HiltTestRunner { *; }
-keep class com.silent.vpn.MainViewModel { *; }
-keep class com.silent.vpn.service.** { *; }
-keep class com.silent.vpn.vpn.** { *; }
-keep class com.silent.vpn.security.** { *; }
-keep class com.silent.vpn.di.** { *; }
-keep class com.silent.vpn.data.** { *; }
-keep class com.silent.vpn.auth.** { *; }
-keep class com.silent.vpn.update.** { *; }
-keep class com.silent.vpn.sync.** { *; }
-keep class com.silent.vpn.policy.** { *; }
-keep class com.silent.vpn.vk.** { *; }

# UI — можно обфусцировать имена классов Compose-экранов, но поля/методы оставляем
# (Gson/Compose иногда завязаны на имена; safe: keep ui package)
-keep class com.silent.vpn.ui.** { *; }
-keep class com.silent.vpn.util.** { *; }

# WireGuard
-keep class com.wireguard.** { *; }

# Retrofit / OkHttp
-keep class retrofit2.** { *; }
-keep interface retrofit2.** { *; }
-keepclasseswithmembers class * { @retrofit2.http.* <methods>; }
-keep class okhttp3.** { *; }
-keep interface okhttp3.** { *; }
-dontwarn okhttp3.**

# Gson
-keep class com.google.gson.** { *; }
-keepclassmembers,allowobfuscation class * { @com.google.gson.annotations.SerializedName <fields>; }

# Усложнить reverse-engineering имён (безопасный режим — без overloadaggressively)
-allowaccessmodification
