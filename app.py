import os
import pandas as pd
import requests
from flask import Flask, render_template_string, jsonify
from google.transit import gtfs_realtime_pb2

app = Flask(__name__)

# ---------------------------------
# CONFIG
# ---------------------------------
FEED_URL = "https://api.wmata.com/gtfs/bus-gtfsrt-vehiclepositions.pb?api_key=b2096c130daf45bbbf6657d650e8d3a4" # Replace with your GTFS-RT feed
STATIC_GTFS = "static_gtfs"
REFRESH_SECONDS = 30

# ---------------------------------
# LOAD STATIC GTFS
# ---------------------------------

def load_static_gtfs():
    routes = pd.read_csv(os.path.join(STATIC_GTFS, "routes.txt"))
    stops  = pd.read_csv(os.path.join(STATIC_GTFS, "stops.txt"))
    trips  = pd.read_csv(os.path.join(STATIC_GTFS, "trips.txt"))

    route_lookup = routes.set_index("route_id").to_dict(orient="index")
    stop_lookup  = stops.set_index("stop_id").to_dict(orient="index")
    trip_lookup  = trips.set_index("trip_id").to_dict(orient="index")
    return route_lookup, stop_lookup, trip_lookup

ROUTE_LOOKUP, STOP_LOOKUP, TRIP_LOOKUP = load_static_gtfs()


# ---------------------------------
# GTFS-RT FETCH
# ---------------------------------

def fetch_gtfs_rt():
    feed = gtfs_realtime_pb2.FeedMessage()
    resp = requests.get(FEED_URL)
    resp.raise_for_status()
    feed.ParseFromString(resp.content)
    return feed


# ---------------------------------
# API ENDPOINTS (JSON)
# ---------------------------------

@app.route("/api/vehicles")
def api_vehicles():
    feed = fetch_gtfs_rt()
    vehicles = []

    for e in feed.entity:
        if e.HasField("vehicle"):
            v = e.vehicle
            trip_id = v.trip.trip_id
            route_id = TRIP_LOOKUP.get(trip_id, {}).get("route_id", "")

            route_name = ""
            if route_id in ROUTE_LOOKUP:
                r = ROUTE_LOOKUP[route_id]
                route_name = r.get("route_short_name") or r.get("route_long_name") or ""

            vehicles.append({
                "id": e.id,
                "lat": v.position.latitude,
                "lon": v.position.longitude,
                "route_name": route_name,
                "trip_id": trip_id,
                "vehicle_label": v.vehicle.label
            })

    return jsonify(vehicles)


@app.route("/api/trip_updates")
def api_trip_updates():
    feed = fetch_gtfs_rt()
    trips = []

    for e in feed.entity:
        if e.HasField("trip_update"):
            tu = e.trip_update
            trip_id = tu.trip.trip_id
            route_id = TRIP_LOOKUP.get(trip_id, {}).get("route_id", "")

            route_name = ""
            if route_id in ROUTE_LOOKUP:
                r = ROUTE_LOOKUP[route_id]
                route_name = r.get("route_short_name") or r.get("route_long_name") or ""

            stops = []
            for stu in tu.stop_time_update:
                stop_name = STOP_LOOKUP.get(stu.stop_id, {}).get("stop_name", "")
                stops.append({
                    "stop_id": stu.stop_id,
                    "stop_name": stop_name,
                    "arrival": getattr(stu.arrival, "time", None),
                    "departure": getattr(stu.departure, "time", None),
                })

            trips.append({
                "id": e.id,
                "trip_id": trip_id,
                "route_name": route_name,
                "stop_updates": stops
            })

    return jsonify(trips)


@app.route("/api/alerts")
def api_alerts():
    feed = fetch_gtfs_rt()
    alerts = []

    for e in feed.entity:
        if e.HasField("alert"):
            a = e.alert
            alerts.append({
                "id": e.id,
                "header": a.header_text.translation[0].text if a.header_text.translation else "",
                "description": a.description_text.translation[0].text if a.description_text.translation else "",
                "cause": a.cause,
                "effect": a.effect,
            })

    return jsonify(alerts)


# ---------------------------------
# FRONTEND PAGE WITH LEAFLET MAP
# ---------------------------------

TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
  <title>GTFS-RT Live Map</title>

  <!-- Leaflet CSS + JS -->
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>

  <style>
    body { margin: 0; font-family: Arial; }
    #map { height: 100vh; width: 100vw; }
    .label {
      background: white;
      padding: 2px 4px;
      border: 1px solid #888;
      border-radius: 3px;
      font-size: 12px;
    }
  </style>
</head>
<body>

<div id="map"></div>

<script>

const refreshSeconds = {{refresh}};

// --------------------------------------------------
// INIT LEAFLET MAP
// --------------------------------------------------
const map = L.map("map").setView([38.9,-76.8], 12); // default center

L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
  maxZoom: 19
}).addTo(map);

// Vehicle icons
const busIcon = L.icon({
  iconUrl: "/static/vehicle.png",
  iconSize: [16,16],
  iconAnchor: [16, 16]
});

// Store vehicle markers
const vehicleMarkers = {};


// --------------------------------------------------
// FETCH VEHICLE DATA AND UPDATE MAP
// --------------------------------------------------
async function updateVehicles() {
  const resp = await fetch("/api/vehicles");
  const data = await resp.json();

  data.forEach(v => {
    const id = v.id;

    // If marker exists → move it
    if (vehicleMarkers[id]) {
      vehicleMarkers[id].setLatLng([v.lat, v.lon]);
    }
    else {
      // Create marker
      const marker = L.marker([v.lat, v.lon], { icon: busIcon })
        .bindPopup(
          "<b>Vehicle:</b> " + v.vehicle_label +
          "<br><b>Route:</b> " + v.route_name +
          "<br><b>Trip:</b> " + v.trip_id
        )
        .addTo(map);

      vehicleMarkers[id] = marker;
    }
  });
}

// --------------------------------------------------
// AUTO REFRESH LOOP
// --------------------------------------------------
setInterval(updateVehicles, refreshSeconds * 1000);
updateVehicles(); // initial load

</script>
</body>
</html>
"""

@app.route("/")
def home():
    return render_template_string(TEMPLATE, refresh=REFRESH_SECONDS)


if __name__ == "__main__":
    app.run(host='127.0.0.3', port=5000)
