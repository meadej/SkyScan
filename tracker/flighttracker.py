#!/usr/bin/env python3
#
# Copyright (c) 2020 Johan Kanflo (github.com/kanflo)
#
# Permission is hereby granted, free of charge, to any person obtaining
# a copy of this software and associated documentation files (the
# "Software"), to deal in the Software without restriction, including
# without limitation the rights to use, copy, modify, merge, publish,
# distribute, sublicense, and/or sell copies of the Software, and to
# permit persons to whom the Software is furnished to do so, subject to
# the following conditions:
#
# The above copyright notice and this permission notice shall be
# included in all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
# EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
# MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
# NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE
# LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
# OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION
# WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

from sched import scheduler
from typing import *
import socket, select
import argparse
import threading
import json
import sys
import os
import logging
import coloredlogs
import calendar
from datetime import datetime, timedelta
import signal
import random
import time
import re
import errno
import sbs1
import utils
import paho.mqtt.client as mqtt 
from json.decoder import JSONDecodeError
import pandas as pd
from queue import Queue
from flask import Flask
from flask import render_template
from base_mqtt_pub_sub import BaseMQTTPubSub

ID = str(random.randint(1,100001))

# Clean out observations this often
OBSERVATION_CLEAN_INTERVAL = 10
# Socket read timeout
DUMP1090_SOCKET_TIMEOUT = 60
q=Queue() # Good writeup of how to pass messages from MQTT into classes, here: http://www.steves-internet-guide.com/mqtt-python-callbacks/
args = None
camera_latitude = None
plant_topic = None # the onMessage function needs to be outside the Class and it needs to get the Plane Topic, so it prob needs to be a global
config_topic = "skyscan/config/json"
camera_longitude = None
camera_altitude = None
camera_lead = None
min_elevation = None
min_altitude = None
max_altitude = None
min_distance = None
max_distance = None
aircraft_pinned = None
tracker = None

app = Flask(__name__)

# http://stackoverflow.com/questions/1165352/fast-comparison-between-two-python-dictionary
class DictDiffer(object):
    """
    Calculate the difference between two dictionaries as:
    (1) items added
    (2) items removed
    (3) keys same in both but changed values
    (4) keys same in both and unchanged values
    """
    def __init__(self, current_dict, past_dict):
        self.current_dict, self.past_dict = current_dict, past_dict
        self.set_current, self.set_past = set(current_dict.keys()), set(past_dict.keys())
        self.intersect = self.set_current.intersection(self.set_past)

    def added(self):
        return self.set_current - self.intersect

    def removed(self):
        return self.set_past - self.intersect

    def changed(self):
        return set(o for o in self.intersect if self.past_dict[o] != self.current_dict[o])

    def unchanged(self):
        return set(o for o in self.intersect if self.past_dict[o] == self.current_dict[o])


class Observation(object):
    """
    This class keeps track of the observed flights around us.
    """
    __icao24 = None
    __loggedDate = None
    __callsign = None
    __altitude = None
    __altitudeTime = None
    __groundSpeed = None
    __track = None
    __lat = None
    __lon = None
    __latLonTime = None
    __verticalRate = None
    __operator = None
    __registration = None
    __type = None
    __manufacturer = None
    __model = None
    __updated = None
    __distance = None
    __bearing = None
    __elevation = None
    __planedb_nagged = False  # Used in case the icao24 is unknown and we only want to log this once
    __onGround = None

    def __init__(self, sbs1msg):

        self.__icao24 = sbs1msg["icao24"].lower() #lets always keep icao24 in lower case
        self.__loggedDate = datetime.utcnow()  # sbs1msg["loggedDate"]
        self.__callsign = sbs1msg["callsign"]
        self.__altitude = sbs1msg["altitude"]
        self.__altitudeTime = datetime.utcnow()
        self.__groundSpeed = sbs1msg["groundSpeed"]
        self.__track = sbs1msg["track"]
        self.__lat = sbs1msg["lat"]
        self.__lon = sbs1msg["lon"]
        self.__latLonTime = datetime.utcnow()
        self.__verticalRate = sbs1msg["verticalRate"]
        self.__onGround = sbs1msg["onGround"]
        self.__operator = None
        self.__registration = None
        self.__type = None
        self.__model = None
        self.__manufacturer = None
        self.__updated = True
        plane = planes.loc[planes['icao24'] == self.__icao24]
        
        if plane.size == 27: # There are 27 columns in CSV file. If it found the plane, it will have 27 keys
            
            logging.info("{}\t[ADDED]\t\t{} {} {} {} {}".format(self.__icao24.lower(), plane["registration"].values[0],plane["manufacturername"].values[0], plane["model"].values[0], plane["operator"].values[0], plane["owner"].values[0]))

            self.__registration = plane['registration'].values[0]
            self.__type = str(plane['manufacturername'].values[0]) + " " + str(plane['model'].values[0])
            self.__manufacturer = plane['manufacturername'].values[0] 
            self.__model =  plane['model'].values[0] 
            self.__operator = plane['operator'].values[0] 
        else:
            if not self.__planedb_nagged:
                self.__planedb_nagged = True
                logging.error("%s\t Not found in the database" % (self.__icao24))
                

    
    def update(self, sbs1msg):
        """ Updates information about a plane from an SBS1 message """

        oldData = dict(self.__dict__) # save existing data to determine if anything has changed
        self.__loggedDate = datetime.utcnow()

        if sbs1msg["icao24"]:
            self.__icao24 = sbs1msg["icao24"].lower() # Let's always keep icao24 in lower case
        if sbs1msg["callsign"] and self.__callsign != sbs1msg["callsign"]:
            self.__callsign = sbs1msg["callsign"].rstrip()
        if sbs1msg["altitude"] is not None:
            if self.__altitude != sbs1msg["altitude"]:
                self.__altitude = sbs1msg["altitude"]
                self.__altitudeTime = sbs1msg["generatedDate"]
        if sbs1msg["groundSpeed"] is not None:
            self.__groundSpeed = sbs1msg["groundSpeed"]
        if sbs1msg["track"] is not None:
            self.__track = sbs1msg["track"]
        if sbs1msg["onGround"] is not None:
            self.__onGround = sbs1msg["onGround"]
        if sbs1msg["lat"] is not None:
            self.__lat = sbs1msg["lat"]
            self.__latLonTime = sbs1msg["generatedDate"]
        if sbs1msg["lon"] is not None:
            self.__lon = sbs1msg["lon"]
            self.__latLonTime = sbs1msg["generatedDate"]
        if sbs1msg["verticalRate"] is not None:
            self.__verticalRate =  sbs1msg["verticalRate"]

        if not self.__verticalRate:
            self.__verticalRate = 0

 
        if self.__lat and self.__lon and self.__altitude and self.__track:
            # Calculates the distance from the cameras location to the airplane. The output is in METERS!
            distance3d = utils.coordinate_distance_3d(camera_latitude, camera_longitude, camera_altitude, self.__lat, self.__lon, self.__altitude)
            distance2d = utils.coordinate_distance(camera_latitude, camera_longitude,  self.__lat, self.__lon )
            

            self.__distance = distance3d  
            self.__bearing = utils.bearingFromCoordinate(cameraPosition=[camera_latitude, camera_longitude], airplanePosition=[self.__lat, self.__lon], heading=self.__track)
            self.__elevation = utils.elevation(distance2d, cameraAltitude=camera_altitude, airplaneAltitude=self.__altitude) # Distance and Altitude are both in meters
        
        # Check if observation was updated
        newData = dict(self.__dict__)
        #del oldData["_Observation__loggedDate"]
        #del newData["_Observation__loggedDate"]
        d = DictDiffer(oldData, newData)
        self.__updated = len(d.changed()) > 0

    def getIcao24(self) -> str:
        return self.__icao24

    def getLat(self) -> float:
        return self.__lat

    def getLon(self) -> float:
        return self.__lon

    def isUpdated(self) -> bool:
        return self.__updated

    def getElevation(self) -> int:
        return self.__elevation

    def getDistance(self) -> int:
        return self.__distance

    def getLoggedDate(self) -> datetime:
        return self.__loggedDate

    def getLatLonTime(self) -> datetime:
        return self.__latLonTime
    
    def getAltitudeTime(self) -> datetime:
        return self.__altitudeTime

    def getGroundSpeed(self) -> float:
        return self.__groundSpeed

    def getTrack(self) -> float:
        return self.__track

    def getOnGround(self) -> bool:
        return self.__onGround

    def getAltitude(self) -> float:
        if self.getOnGround():
            self.__altitude = camera_altitude
        return self.__altitude

    def getType(self) -> str:
        return self.__type

    def getManufacturer(self) -> str:
        return self.__manufacturer

    def getModel(self) -> str:
        return self.__model

    def getRegistration(self) -> str:
        return self.__registration

    def getOperator(self) -> str:
        return self.__operator

    def getRoute(self) -> str:
        return self.__route
    
    def getVerticalRate(self) -> float:
        return self.__verticalRate

    def isPresentable(self) -> bool:
        return self.__altitude and self.__groundSpeed and self.__track and self.__lat and self.__lon and self.__distance

    def dump(self):
        """Dump this observation on the console
        """
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')
        logging.debug("> %s  %s %-7s - trk:%3d spd:%3d alt:%5d (%5d) %.4f, %.4f" % (now, self.__icao24, self.__callsign, self.__track, self.__groundSpeed, self.__altitude, self.__verticalRate, self.__lat, self.__lon))


    def json(self) -> str:
        """Return JSON representation of this observation
        
        Arguments:
            bearing {float} -- bearing to observation in degrees
            distance {int} -- distance to observation in meters
        
        Returns:
            str -- JSON string
        """

        if self.__callsign is None:
            callsign = "None"
        else:
            callsign = "\"%s\"" % self.__callsign

        planeDict = {"verticalRate": self.__verticalRate, "time": time.time(), "lat": self.__lat, "lon": self.__lon,  "altitude": self.__altitude, "groundSpeed": self.__groundSpeed, "icao24": self.__icao24, "registration": self.__registration, "track": self.__track, "operator": self.__operator,   "loggedDate": self.__loggedDate, "type": self.__type, "latLonTime": self.__latLonTime, "altitudeTime": self.__altitudeTime, "manufacturer": self.__manufacturer, "model": self.__model, "callsign": callsign, "bearing": self.__bearing, "distance": self.__distance, "elevation": self.__elevation}
        jsonString = json.dumps(planeDict, indent=4, sort_keys=True, default=str)
        return jsonString

    def dict(self):
        d =  dict(self.__dict__)
        if d["_Observation__verticalRate"] == None:
            d["verticalRate"] = 0
        if "_Observation__lastAlt" in d:
            del d["lastAlt"]
        if "_Observation__lastLat" in d:
            del d["lastLat"]
        if "_Observation__lastLon" in d:
            del d["lastLon"]
        return d



def update_config(config):
    """ Adjust configuration values based on MQTT config messages that come in """
    global camera_lead
    global min_elevation
    global min_distance
    global min_altitude
    global min_elevation
    global max_altitude
    global max_distance
    global aircraft_pinned


    if "cameraLead" in config:
        camera_lead = float(config["cameraLead"])
        logging.info("Setting Camera Lead to: {}".format(camera_lead))
    if "minElevation" in config:
        min_elevation = int(config["minElevation"])
        logging.info("Setting Min. Elevation to: {}".format(min_elevation))
    if "minDistance" in config:
        min_distance = int(config["minDistance"])
        logging.info("Setting Min. Distance to: {}".format(min_distance))
    if "minAltitude" in config:
        min_altitude = int(config["minAltitude"])
        logging.info("Setting Min. Altitude to: {}".format(min_altitude))
    if "maxAltitude" in config:
        max_altitude = int(config["maxAltitude"])
        logging.info("Setting Max Altitude to: {}".format(max_altitude))                    
    if "maxDistance" in config:
        max_distance = int(config["maxDistance"])
        logging.info("Setting Max Distance to: {}".format(min_elevation))
    if "aircraftPinned" in config:
        aircraft_pinned = config["aircraftPinned"].lower()
        logging.info("Pinning Aircraft to: {}".format(aircraft_pinned))
        
def on_message(client, userdata, message):
    """ MQTT Client callback for new messages """

    global camera_altitude
    global camera_latitude
    global camera_longitude

    command = str(message.payload.decode("utf-8"))
    # Assumes you will only be getting JSON on your subscribed messages
    try:
        update = json.loads(command)
    except JSONDecodeError as e:
        logging.critical("onMessage - JSONDecode Error: {} ".format(e))
    except TypeError as e:
        logging.critical("onMessage - Type Error: {} ".format(e))
    except ValueError as e:
        logging.critical("onMessage - Value Error: {} ".format(e))
    except:
        logging.critical("onMessage - Caught it!")

    if message.topic == "skyscan/egi":
        #logging.info(update)
        camera_longitude = float(update["long"])
        camera_latitude = float(update["lat"])
        camera_altitude = float(update["alt"])
    elif message.topic == config_topic:
        update_config(update)
        logging.info("Config Message: {}".format(update))
    else:
        logging.info("Topic not processed: " + message.topic)
   
class FlightTracker(BaseMQTTPubSub):
    _flight_topic: str = None
    _client = None
    _observations: Dict[str, str] = {}
    _tracking_icao24: str = None
    _tracking_distance: int = 999999999
    _next_clean: datetime = None
    __has_nagged: bool = False
    _dump1090_host: str = ""
    _dump1090_port: int = 0
    __dump1090_sock: socket.socket = None

    def __init__(self, dump1090_host: str, flight_topic: str, mqtt_ip: str, dump1090_port: int = 30003, mqtt_port: int = 1883, **kwargs):
        """Initialize the flight tracker

        Arguments:
            dump1090_host {str} -- Name or IP of dump1090 host
            mqtt_ip {str} -- Name or IP of dump1090 MQTT broker
            latitude {float} -- Latitude of receiver
            longitude {float} -- Longitude of receiver
            plane_topic {str} -- MQTT topic for plane reports
            flight_topic {str} -- MQTT topic for current tracking report

        Keyword Arguments:
            dump1090_port {int} -- Override the dump1090 raw port (default: {30003})
            mqtt_port {int} -- Override the MQTT default port (default: {1883})
        """
        super().__init__(**kwargs)
        self.mqtt_ip = mqtt_ip
        self.mqtt_port = mqtt_port

        self.connect_client()

        self._dump1090_host = dump1090_host
        self._dump1090_port = dump1090_port
        self._observations = {}
        self._next_clean = datetime.utcnow() + timedelta(seconds=OBSERVATION_CLEAN_INTERVAL)
        self._flight_topic = flight_topic

    def _getObservationJson(self, observation):
        (lat, lon, alt) = utils.calc_travel_3d(observation.getLat(), observation.getLon(), observation.getAltitude(), observation.getLatLonTime(), observation.getAltitudeTime(), observation.getGroundSpeed(), observation.getTrack(), observation.getVerticalRate(), camera_lead)
        distance3d = utils.coordinate_distance_3d(camera_latitude, camera_longitude, camera_altitude, lat, lon, alt)
        #(latorig, lonorig) = utils.calc_travel(observation.getLat(), observation.getLon(), observation.getLatLonTime(),  observation.getGroundSpeed(), observation.getTrack(), camera_lead)
        distance2d = utils.coordinate_distance(camera_latitude, camera_longitude, lat, lon)
        bearing = utils.bearingFromCoordinate( cameraPosition=[camera_latitude, camera_longitude], airplanePosition=[lat, lon], heading=observation.getTrack())
        elevation = utils.elevation(distance2d, cameraAltitude=camera_altitude, airplaneAltitude=alt) 
        cameraTilt = elevation
        cameraPan = utils.cameraPanFromCoordinate(cameraPosition=[camera_latitude, camera_longitude], airplanePosition=[lat, lon])
        #elevationorig = utils.elevation(distance2d, observation.getAltitude(), camera_altitude) 
        return observation.json()

    def _publish_thread(self):
        """
        MQTT publish closest observation every second, more often if the plane is closer
        """
        timeHeartbeat = 0
        notTrackingJson = "{}"

        while True:

            # Checks to see if it is time to publish a hearbeat message
            if timeHeartbeat < time.mktime(time.gmtime()):
                timeHeartbeat = time.mktime(time.gmtime()) + 10
                self._client.publish("skyscan/heartbeat", "skyscan-tracker-" +ID+" Heartbeat", 0, False)

            # if we are not tracking anything, goto sleep for 1 second
            if not self._tracking_icao24:
                retain = False
                self._client.publish(self._flight_topic, notTrackingJson, 0, retain)
                delay = 1
                time.sleep(delay)
            else:
                # Check to see if the currently tracked airplane is in the observations
                if not self._tracking_icao24 in self._observations:
                    self._tracking_icao24 = None
                    continue
                cur = self._observations[self._tracking_icao24]
                if cur is None:
                    continue
                retain = False
                self._client.publish(self._flight_topic, cur.json(), 0, retain)
                

                if self._tracking_distance < 3000:
                    delay = 0.25
                elif self._tracking_distance < 6000:
                    delay = 0.5
                else:
                    delay = 1
                time.sleep(delay)

    def _whyTrackable(self, observation) -> str:
        """ Returns a string explaining why a Plane can or cannot be tracked """

        reason = ""

        if observation.getAltitude() == None or observation.getGroundSpeed() == None or observation.getTrack() == None or observation.getLat() == None or observation.getLon() == None:
            reason = "Loc: ⛔️" 
        else:
            reason = "Loc: ✅" 

        if observation.getOnGround() == True:
            reason = reason + "\tGrnd: ⛔️" 
        else:
            reason = reason + "\tGrnd: ✅" 
        
        if max_altitude != None and observation.getAltitude() > max_altitude:
            reason = reason + "\tMax Alt: ⛔️" 
        else:
            reason = reason + "\tMax Alt: ✅" 

        if min_altitude != None and observation.getAltitude() < min_altitude:
            reason = reason + "\tMin Alt: ⛔️" 
        else:
            reason = reason + "\tMin Alt: ✅" 

        if observation.getDistance() == None or observation.getElevation() == None:
            return False

        if min_distance != None and observation.getDistance() < min_distance:
            reason = reason + "\tMin Dist: ⛔️" 
        else:
            reason = reason + "\tMin Dist: ✅" 

        if max_distance != None and observation.getDistance() > max_distance:
            reason = reason + "\tMax Dist: ⛔️" 
        else:
            reason = reason + "\tMax Dist: ✅" 
        
        if observation.getElevation() < min_elevation:
            reason = reason + "\tMin Elv: ⛔️" 
        else:
            reason = reason + "\tMin Elv: ✅" 

        return reason

    def _isTrackable(self, observation) -> bool:
        """ Does this observation meet all of the requirements to be tracked """

        if observation.getAltitude() == None or observation.getGroundSpeed() == None or observation.getTrack() == None or observation.getLat() == None or observation.getLon() == None:
            return False 

        if observation.getOnGround() == True:
            return False
        
        if max_altitude != None and observation.getAltitude() > max_altitude:
            return False

        if min_altitude != None and observation.getAltitude() < min_altitude:
            return False

        if observation.getDistance() == None or observation.getElevation() == None:
            return False

        if min_distance != None and observation.getDistance() < min_distance:
            return False

        if max_distance != None and observation.getDistance() > max_distance:
            return False
        
        if observation.getElevation() < min_elevation:
            return False

        return True

    def _updateTrackingDistance(self):
        """Update distance to aircraft being tracked
        """
        cur = self._observations[self._tracking_icao24]
        if cur.getAltitude():
            self._tracking_distance = utils.coordinate_distance_3d(camera_latitude, camera_longitude, camera_altitude, cur.getLat(), cur.getLon(), cur.getAltitude())

    def _observationKey(self,obs):

        return int(obs["_Observation__distance"])


    def getObservations(self):
        items=[]
        for icao24 in self._observations:
            if self._observations[icao24].isPresentable():
                items.append(self._observations[icao24].dict())
        items.sort(key=self._observationKey)
        return items

    def getTracking(self):
        return self._tracking_icao24

    def getTrackingObservation(self):
        return self._getObservationJson(self._observations[self._tracking_icao24])


    def dump1090Connect(self) -> bool:
        """If not connected, connect to the dump1090 host

        Returns:
            bool -- True if we are connected
        """
        if self.__dump1090_sock == None:
            try:
                if not self.__has_nagged:
                    logging.info("Connecting to dump1090")
                self.__dump1090_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.__dump1090_sock.connect((self._dump1090_host, self._dump1090_port))
                logging.info("ADSB connected")
                self.__dump1090_sock.settimeout(DUMP1090_SOCKET_TIMEOUT)
                self.__has_nagged = False
                return True
            except socket.error as e:
                if not self.__has_nagged:
                    logging.critical("Failed to connect to ADSB receiver on %s:%s, retrying : %s" % (self._dump1090_host, self._dump1090_port, e))
                    self.__has_nagged = True
                self.__dump1090_sock = None
                delay = 5
                time.sleep(delay)
            return False
        else:
            return True


    def dump1090Close(self):
        """Close connection to dump1090 host.
        """
        try:
            self.__dump1090_sock.close()
        except socket.error:
            pass
        self.__dump1090_sock = None
        self.__has_nagged = False
        logging.critical("Closing dump1090 connection")


    def dump1090Read(self) -> str:
        """Read a line from the dump1090 host. If the host went down, close the socket and return None

        Returns:
            str -- An SBS1 message or None if disconnected or timeout

        Yields:
            str -- An SBS1 message or None if disconnected or timeout
        """
        try:
            try:
                buffer = self.__dump1090_sock.recv(4096)
            except ConnectionResetError:
                logging.critical("Connection Reset Error")
                self.dump1090Close()
                return None
            except socket.error:
                logging.critical("Socket Error")
                self.dump1090Close()
                return None
            buffer = buffer.decode("utf-8")
            buffering = True
            if buffer == "":
                logging.critical("Buffer Empty")
                self.dump1090Close()
                return None
            while buffering:
                if "\n" in buffer:
                    (line, buffer) = buffer.split("\r\n", 1)
                    yield line
                else:
                    try:
                        more = self.__dump1090_sock.recv(4096)
                    except ConnectionResetError:
                        logging.critical("Connection Reset Error")
                        self.dump1090Close()
                        return None
                    except socket.error:
                        logging.critical("Socket Error")
                        self.dump1090Close()
                        return None
                    if not more:
                        buffering = False
                    else:
                        if not isinstance(more, str):
                            more = more.decode("utf-8")
                        if more == "":
                            logging.critical("Receive Empty")
                            self.dump1090Close()
                            return None
                        buffer += more
            if buffer:
                yield buffer
        except socket.timeout:
            return None

    def run(self):
        """
        Run the flight tracker.
        """
        global aircraft_pinned

        self._client.on_message = on_message #attach function to callback
        self._client.loop_start() #start the loop

        self.add_subscribe_topic("skyscan/egi")
        self.add_subscribe_topic(config_topic)
        self.publish_registration("skyscan-tracker-" + ID + " Registration")

        threading.Thread(target = self._publish_thread, daemon = True).start()

        scheduler.every(10).seconds.do(
            self.publish_heartbeat, payload="Flighttracker C2 Heartbeat"
        )

        # This loop reads in new messages from dump1090 and determines which plane to track
        while True:
            if not self.dump1090Connect():
                continue

            for data in self.dump1090Read():
                if data is None:
                    continue

                self._cleanObservations()

                sbs_data = sbs1.parse(data)

                if sbs_data:
                    icao24 = sbs_data["icao24"].lower()

                    # Add or update the Observation for the plane
                    if icao24 not in self._observations:
                        self._observations[icao24] = Observation(sbs_data)
                    else:
                        self._observations[icao24].update(sbs_data)
                    
                    if bool(aircraft_pinned) & (aircraft_pinned not in self._observations):
                        aircraft_pinned = None

                    # if the pinned_aircraft variable is set and that the plane is the pinned aircraft    
                    if (bool(aircraft_pinned)) & (icao24 == aircraft_pinned):
                        if aircraft_pinned != self._tracking_icao24:
                            self._tracking_icao24 = icao24
                            self._updateTrackingDistance()
                            logging.info("{}\t[PINNED AIRCRAFT TRACKING]\tDist: {}\tElev: {}\t\t".format(self._tracking_icao24, self._tracking_distance, self._observations[icao24].getElevation()))
                        else:
                            self._updateTrackingDistance()
                    
                    # if the plane is suitable to be tracked        
                    elif (not bool(aircraft_pinned)) & self._isTrackable(self._observations[icao24]):

                        # if no plane is being tracked, track this one
                        if not self._tracking_icao24:
                            self._tracking_icao24 = icao24
                            self._updateTrackingDistance()
                            logging.info("{}\t[TRACKING]\tDist: {}\tElev: {}\t\t".format(self._tracking_icao24, self._tracking_distance, self._observations[icao24].getElevation()))
          
                        # if this is the plane being tracked, update the tracking distance
                        elif self._tracking_icao24 == icao24:
                            self._updateTrackingDistance()
                        
                        # This plane is trackable, but is not the one being tracked
                        else:
                            distance = self._observations[icao24].getDistance()
                            if distance < self._tracking_distance:
                                self._tracking_icao24 = icao24
                                self._tracking_distance = distance
                                logging.info("{}\t[TRACKING]\tDist: {}\tElev: {}\t\t - Switched to closer plane".format(self._tracking_icao24, int(self._tracking_distance), int(self._observations[icao24].getElevation())))
                    else:
                        # If the plane is currently being tracked, but is no longer trackable:
                        if self._tracking_icao24 == icao24:
                            logging.info("%s\t[NOT TRACKING]\t - Observation is no longer trackable" % (icao24))
                            logging.info(self._whyTrackable(self._observations[icao24]))
                            self._tracking_icao24 = None
                            self._tracking_distance = 999999999
            
            delay = 0.01                                     
            time.sleep(delay)

    def _selectNearestObservation(self):
        """Select nearest presentable aircraft
        """
        self._tracking_icao24 = None
        self._tracking_distance = 999999999
        for icao24 in self._observations:
            if not self._isTrackable(self._observations[icao24]):
                continue
            distance = self._observations[icao24].getDistance()
            if self._observations[icao24].getDistance() < self._tracking_distance:
                self._tracking_icao24 = icao24
                self._tracking_distance = distance
        if self._tracking_icao24:
            logging.info("{}\t[TRACKING]\tDist: {}\t\t - Selected Nearest Observation".format(self._tracking_icao24, self._tracking_distance))
            

    def _cleanObservations(self):
        global aircraft_pinned
        """Clean observations for planes not seen in a while
        """
        now = datetime.utcnow()
        if now > self._next_clean:
            cleaned = []
            for icao24 in self._observations:
#                logging.info("[%s] %s -> %s : %s" % (icao24, self.__observations[icao24].getLoggedDate(), self.__observations[icao24].getLoggedDate() + timedelta(seconds=OBSERVATION_CLEAN_INTERVAL), now))
                if self._observations[icao24].getLoggedDate() + timedelta(seconds=OBSERVATION_CLEAN_INTERVAL) < now:
                    logging.info("%s\t[REMOVED]\t" % (icao24))
                    if icao24 == aircraft_pinned:
                        aircraft_pinned = None
                        logging.info("%s\t[REMOVED PINNED AIRCRAFT - REVERTING TO NORMAL TRACKING]\t" % (icao24))
                    if icao24 == self._tracking_icao24:
                        self._tracking_icao24 = None
                        self._tracking_distance = 999999999
                    cleaned.append(icao24)
                if icao24 == self._tracking_icao24 and not self._isTrackable(self._observations[icao24]) and not aircraft_pinned:
                    logging.info("%s\t[NOT TRACKING]\t - Observation is no longer trackable" % (icao24))
                    logging.info(self._whyTrackable(self._observations[icao24]))
                    self._tracking_icao24 = None
                    self._tracking_distance = 999999999
            for icao24 in cleaned:
                del self._observations[icao24]
            if self._tracking_icao24 is None:
                self._selectNearestObservation()

            self._next_clean = now + timedelta(seconds=OBSERVATION_CLEAN_INTERVAL)


def getConfig():
    config ={}
    config["camera_altitude"] = camera_altitude
    config["camera_latitude"] = camera_latitude
    config["camera_longitude"] = camera_longitude
    config["camera_lead"] = camera_lead
    config["min_elevation"] = min_elevation
    config["min_distance"] = min_distance
    config["max_distance"] = max_distance
    config["min_altitude"] = min_altitude
    config["max_altitude"] = max_altitude
    config["aircraft_pinned"] = aircraft_pinned
    return config




@app.route('/')
def index():
    return render_template('index.html', title='SkyScan', tracking=tracker.getTracking(), observations=tracker.getObservations(), config=getConfig())



def main():
    global args
    global logging
    global camera_altitude
    global camera_latitude
    global camera_longitude
    global camera_lead
    global plane_topic
    global min_elevation
    global planes
    global tracker
    parser = argparse.ArgumentParser(description='A Dump 1090 to MQTT bridge')


    parser.add_argument('-l', '--lat', type=float, help="Latitude of camera")
    parser.add_argument('-L', '--lon', type=float, help="Longitude of camera")
    parser.add_argument('-a', '--alt', type=float, help="altitude of camera in METERS!", default=0)
    parser.add_argument('-c', '--camera-lead', type=float, help="how many seconds ahead of a plane's predicted location should the camera be positioned", default=0.25)
    parser.add_argument('-M', '--min-elevation', type=int, help="minimum elevation for camera", default=0)
    parser.add_argument('-m', '--mqtt-host', help="MQTT broker hostname", default='127.0.0.1')
    parser.add_argument('-p', '--mqtt-port', type=int, help="MQTT broker port number (default 1883)", default=1883)
    parser.add_argument('-T', '--flight-topic', dest='flight_topic', help="MQTT flight tracking topic", default="skyscan/flight/json")
    parser.add_argument('-v', '--verbose',  action="store_true", help="Verbose output")
    parser.add_argument('-H', '--dump1090-host', help="dump1090 hostname", default='127.0.0.1')
    parser.add_argument('--dump1090-port', type=int, help="dump1090 port number (default 30003)", default=30003)
 
    args = parser.parse_args()

    if not args.lat and not args.lon:
        logging.critical("You really need to tell me where you are located (--lat and --lon)")
        sys.exit(1)
    camera_longitude = args.lon
    camera_latitude = args.lat
    camera_altitude = args.alt # Altitude is in METERS
    plane_topic = args.plane_topic
    camera_lead = args.camera_lead
    min_elevation = args.min_elevation
    level = logging.DEBUG if args.verbose else logging.INFO

    styles = {'critical': {'bold': True, 'color': 'red'}, 'debug': {'color': 'green'}, 'error': {'color': 'red'}, 'info': {'color': 'white'}, 'notice': {'color': 'magenta'}, 'spam': {'color': 'green', 'faint': True}, 'success': {'bold': True, 'color': 'green'}, 'verbose': {'color': 'blue'}, 'warning': {'color': 'yellow'}}
    level = logging.DEBUG if '-v' in sys.argv or '--verbose' in sys.argv else logging.INFO
    if 1:
        coloredlogs.install(level=level, fmt='%(asctime)s.%(msecs)03d \033[0;90m%(levelname)-8s '
                            ''
                            '\033[0;36m%(filename)-18s%(lineno)3d\033[00m '
                            '%(message)s',
                            level_styles = styles)
    else:
        # Show process name
        coloredlogs.install(level=level, fmt='%(asctime)s.%(msecs)03d \033[0;90m%(levelname)-8s '
                                '\033[0;90m[\033[00m \033[0;35m%(processName)-15s\033[00m\033[0;90m]\033[00m '
                                '\033[0;36m%(filename)s:%(lineno)d\033[00m '
                                '%(message)s')

    logging.info("---[ Starting %s ]---------------------------------------------" % sys.argv[0])
    planes = pd.read_csv("/data/aircraftDatabase.csv") #,index_col='icao24')
    logging.info("Printing table")
    logging.info(planes)

    threading.Thread(target=app.run, kwargs={"host": '0.0.0.0', "port": 5000}).start()

    tracker = FlightTracker(args.dump1090_host, args.mqtt_host, args.flight_topic, dump1090_port = args.dump1090_port, mqtt_ip=args.mqtt_host,  mqtt_port = args.mqtt_port)

    tracker.run()  # Never returns


# Ye ol main
if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logging.critical(e, exc_info=True)
