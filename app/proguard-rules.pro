-dontwarn com.google.errorprone.annotations.**
-dontwarn javax.annotation.**
-dontwarn org.codehaus.mojo.animal_sniffer.*
-dontwarn com.google.crypto.tink.**

# Hilt
-keep class dagger.hilt.** { *; }
-keep class javax.inject.** { *; }
-keep @dagger.hilt.android.lifecycle.HiltViewModel class * { *; }
-keep class * extends androidx.lifecycle.ViewModel { *; }
-keep class com.silent.vpn.** { *; }

-keep class com.silent.vpn.data.** { *; }
-keep class com.wireguard.** { *; }
-keep class com.silent.vpn.vpn.** { *; }
-keepattributes *Annotation*
-keepattributes Signature

# Retrofit
-keepattributes Exceptions
-keep class retrofit2.** { *; }
-keep interface retrofit2.** { *; }
-keepclasseswithmembers class * { @retrofit2.http.* <methods>; }

# OkHttp
-keep class okhttp3.** { *; }
-keep interface okhttp3.** { *; }
-dontwarn okhttp3.**

# Gson
-keep class com.google.gson.** { *; }
-keepclassmembers,allowobfuscation class * { @com.google.gson.annotations.SerializedName <fields>; }
