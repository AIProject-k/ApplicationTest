package dev.indi.applicationtest;

import android.app.Activity;
import android.graphics.Color;
import android.os.Bundle;
import android.view.Gravity;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.TextView;
import android.widget.Toast;

public class MainActivity extends Activity {
    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        LinearLayout content = new LinearLayout(this);
        content.setOrientation(LinearLayout.VERTICAL);
        content.setGravity(Gravity.CENTER_VERTICAL);
        int padding = (int) (28 * getResources().getDisplayMetrics().density);
        content.setPadding(padding, padding, padding, padding);
        content.setOnApplyWindowInsetsListener((view, insets) -> {
            view.setPadding(padding + insets.getSystemWindowInsetLeft(), padding + insets.getSystemWindowInsetTop(),
                    padding + insets.getSystemWindowInsetRight(), padding + insets.getSystemWindowInsetBottom());
            return insets;
        });
        addText(content, getString(R.string.repository), 14);
        addText(content, getString(R.string.title), 30);
        addText(content, getString(R.string.description), 17);
        addText(content, getString(R.string.version, BuildConfig.VERSION_NAME, BuildConfig.VERSION_CODE), 16);
        addText(content, getString(R.string.package_name, getPackageName()), 13);
        Button check = new Button(this);
        check.setText(R.string.check);
        check.setOnClickListener(view -> Toast.makeText(this, R.string.confirmed, Toast.LENGTH_SHORT).show());
        content.addView(check);
        setContentView(content);
        content.requestApplyInsets();
    }

    private void addText(LinearLayout parent, String text, int size) {
        TextView view = new TextView(this);
        view.setText(text);
        view.setTextSize(size);
        view.setTextColor(Color.rgb(32, 72, 53));
        view.setPadding(0, 12, 0, 18);
        parent.addView(view);
    }
}
