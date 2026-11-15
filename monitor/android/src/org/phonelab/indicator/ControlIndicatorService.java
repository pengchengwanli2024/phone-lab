package org.phonelab.indicator;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.Service;
import android.content.Intent;
import android.os.Handler;
import android.os.IBinder;

/** Silent status-bar indication; never draws over application content. */
public final class ControlIndicatorService extends Service {
    private static final String CHANNEL = "computer_control";
    private final Handler handler = new Handler();
    private final Runnable expire = () -> {
        stopForeground(true);
        stopSelf();
    };

    @Override public int onStartCommand(Intent intent, int flags, int startId) {
        NotificationManager manager = getSystemService(NotificationManager.class);
        NotificationChannel channel = new NotificationChannel(
            CHANNEL, "电脑控制状态", NotificationManager.IMPORTANCE_LOW);
        channel.setSound(null, null);
        channel.enableVibration(false);
        channel.setShowBadge(false);
        manager.createNotificationChannel(channel);
        Notification notification = new Notification.Builder(this, CHANNEL)
            .setSmallIcon(android.R.drawable.presence_online)
            .setContentTitle("电脑控制中")
            .setContentText("本次已授权操作进行中；停止或失去心跳后自动消失。")
            .setOnlyAlertOnce(true)
            .setOngoing(true)
            .setShowWhen(false)
            .build();
        startForeground(1, notification);
        handler.removeCallbacks(expire);
        handler.postDelayed(expire, 90000);
        return START_NOT_STICKY;
    }

    @Override public void onDestroy() {
        handler.removeCallbacks(expire);
        stopForeground(true);
        super.onDestroy();
    }

    @Override public IBinder onBind(Intent intent) { return null; }
}
