from datetime import time, datetime
from django.contrib.gis.geos import LineString, Point
from django.core.management.base import BaseCommand
from django.db import transaction, reset_queries, connection
from mta_data.models import *
from mta_data.utils import st_line_locate_point

import transitfeed

stop_cache = {}
def process_route(feed, gtfs_route):
    direction = gtfs_route.route_long_name[-1]
    long_name = gtfs_route.route_long_name[:-2] #chop off direction
    name = gtfs_route.route_short_name

    reset_queries()
    route_cache = {}
    shape_cache = {}
    for gtfs_trip in gtfs_route.trips:
        #find or create route and shape
        route_id = gtfs_route.route_id
        if route_id in route_cache:
            route = route_cache[route_id]
        else:
            route = list(Route.objects.filter(gid=route_id))
            if route:
                route = route[0]
            else:
                route = Route(gid = route_id,
                              name = name, 
                              headsign = long_name,
                              direction = direction)
                route.save()
            route_cache[route_id] = route

        stop_times = gtfs_trip.GetStopTimes()
        start = stop_times[0].arrival_secs
        hours = start / 3600
        minutes = (start / 60) % 60
        seconds =  start % 60
        day_later = False
        if hours >= 24:
            hours -= 24
            start -= 86400
            day_later = True
        start_time = time(hours, minutes, seconds)


        shape_id = gtfs_trip.shape_id
        if not shape_id:
            continue 
        if shape_id in shape_cache:
            shape = shape_cache[shape_id]
        else:
            shape = list(Shape.objects.filter(gid=shape_id))
            if shape:
                shape = shape[0]
                geometry = shape.geometry
            else:
                
                geometry = LineString([(stop_time.stop.stop_lon, stop_time.stop.stop_lat) for stop_time in stop_times])
                shape = Shape(gid=shape_id,
                              geometry=geometry)
                shape.save()
            shape_cache[shape_id] = shape

        trip = list(Trip.objects.filter(shape=shape, route=route, day_of_week=gtfs_trip.service_id, start_time=start_time))

        if trip:
            print "This trip seems to exist.  That shouldn't happen."
            trip = trip[0]
        else:
            trip = Trip(shape=shape, route=route, day_of_week=gtfs_trip.service_id, start_time=start_time)
            trip.save(force_insert=True)

        last = stop_times[-1]
        first = True
        for stop_time in stop_times:
            stop = stop_time.stop
            bus_stop = stop_cache[stop_time.stop_id]
            #distance = st_line_locate_point(geometry, (stop.stop_lon, stop.stop_lat))
            arrival_secs = stop_time.arrival_secs
            if day_later:
                arrival_secs -= 86400
            type = 'T'
            distance = -1
            if first:
                type = 'D'
                distance = 0
                first = False
            elif stop_time == last:
                type = 'A'
                distance = 1
            ts = TripStop(trip = trip, 
                          seconds_after_start = arrival_secs - start,
                          bus_stop = bus_stop, distance = distance,
                          type=type)
            ts.save()

class Command(BaseCommand):
    """Import mta schedule and route data from GTFS into DB."""

    @transaction.commit_manually
    def handle(self, gtfs_file, **kw):
        try:
            feed = transitfeed.Loader(gtfs_file, memory_db=False).Load()

            for stop_id, stop in feed.stops.items():
                bus_stop = BusStop(box_no=stop_id, location=stop.stop_name,
                                   geometry=Point(stop.stop_lon, stop.stop_lat))
                bus_stop.save()
                stop_cache[stop_id] = bus_stop
            transaction.commit()

            for route_id, route in sorted(feed.routes.items()):
                process_route(feed, route)
                transaction.commit()

            periods = feed.GetServicePeriodList()
            for period in periods:
                service_id = period.service_id
                for date in period.ActiveDates():
                    date = datetime.strptime(date, '%Y%m%d')
                    ScheduleDay(day=date, day_of_week=service_id).save()

            transaction.commit()                

            curs = connection.cursor()

            curs.execute("create temporary table distances(tripstop_id integer primary key, distance float);")
            
            curs.execute ("insert into distances select mta_data_tripstop.id, st_line_locate_point(mta_data_shape.geometry, mta_data_busstop.geometry) from mta_data_tripstop, mta_data_trip, mta_data_shape, mta_data_busstop where bus_stop_id=mta_data_busstop.box_no and mta_data_trip.id = trip_id and mta_data_shape.gid = mta_data_trip.shape_id and mta_data_tripstop.type = 'T';")

            #drop all constraints to make the update complete in a reasonable time
            curs.execute("drop index mta_data_tripstop_bus_stop_id;")
            curs.execute("drop index mta_data_tripstop_trip_id;")
            curs.execute("alter table mta_data_tripstop drop constraint mta_data_tripstop_trip_id_fkey;")
            curs.execute("alter table mta_data_tripstop drop constraint mta_data_tripstop_bus_stop_id_fkey;")

            curs.execute("update mta_data_tripstop set distance=(select distance from distances where tripstop_id=mta_data_tripstop.id) where type = 'T';")

            #and recreate the constraints
            curs.execute("ALTER TABLE mta_data_tripstop ADD CONSTRAINT mta_data_tripstop_bus_stop_id_fkey FOREIGN KEY (bus_stop_id) REFERENCES mta_data_busstop (box_no) MATCH FULL;")
            curs.execute("ALTER TABLE mta_data_tripstop ADD CONSTRAINT mta_data_tripstop_trip_id_fkey FOREIGN KEY (trip_id) REFERENCES mta_data_trip (id) MATCH FULL;")
            curs.execute("CREATE INDEX mta_data_tripstop_bus_stop_id on mta_data_tripstop(bus_stop_id);")
            curs.execute("CREATE INDEX mta_data_tripstop_trip_id on mta_data_tripstop(trip_id);")

            curs.execute("drop table distances;")

            transaction.commit()

        except Exception, e:
            import traceback
            traceback.print_exc()
            import pdb;pdb.set_trace()
            raise
