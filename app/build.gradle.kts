plugins { id("com.android.application") }

android {
    namespace = "dev.indi.applicationtest"
    compileSdk = 36
    defaultConfig {
        applicationId = "dev.indi.applicationtest"
        minSdk = 26
        targetSdk = 36
        versionCode = 1
        versionName = "1.0.0"
    }
    buildTypes {
        release {
            // This repository distributes integration-test builds only.
            signingConfig = signingConfigs.getByName("debug")
            isMinifyEnabled = false
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    buildFeatures { buildConfig = true }
}
