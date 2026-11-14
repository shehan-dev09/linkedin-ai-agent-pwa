// Service Worker for iOS PWA Installation & Push Notifications
const CACHE_NAME = "sn-ai-studio-v1";

self.addEventListener("install", (event) => {
    self.skipWaiting();
});

self.addEventListener("activate", (event) => {
    event.waitUntil(clients.claim());
});

// Listen for notification trigger from the app
self.addEventListener("message", (event) => {
    if (event.data && event.data.type === "NOTIFY_DRAFT_READY") {
        self.registration.showNotification("AI/ML Draft Ready for Review", {
            body: event.data.title || "Tap to review and publish to LinkedIn.",
            icon: "/static/avatar.jpg",
            badge: "/static/avatar.jpg",
            vibrate: [100, 50, 100],
            data: { url: "/" }
        });
    }
});

self.addEventListener("notificationclick", (event) => {
    event.notification.close();
    event.waitUntil(
        clients.openWindow(event.notification.data.url || "/")
    );
});