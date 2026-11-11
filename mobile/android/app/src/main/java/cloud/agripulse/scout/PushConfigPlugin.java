package cloud.agripulse.scout;

import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;

/**
 * Tells the web layer whether this APK was built with Firebase.
 *
 * PushNotifications.register() calls FirebaseMessaging.getInstance(), which
 * throws when no FirebaseApp exists, and Capacitor rethrows a plugin exception
 * on its handler thread, so the app dies rather than rejecting the promise.
 * Without google-services.json, every signed-in launch reached that call and
 * crashed a second after opening. `google_app_id` is the string resource the
 * google-services Gradle plugin generates from that file, so its presence is
 * the same signal Firebase itself uses to auto-initialise.
 */
@CapacitorPlugin(name = "PushConfig")
public class PushConfigPlugin extends Plugin {

    @PluginMethod
    public void status(PluginCall call) {
        int id = getContext().getResources().getIdentifier("google_app_id", "string", getContext().getPackageName());
        JSObject ret = new JSObject();
        ret.put("firebaseConfigured", id != 0);
        call.resolve(ret);
    }
}
