from datetime import datetime, timedelta
from django.test import TestCase
from django.test.client import Client
from tracker.views import update
from tracker.models import *


class UpdateTestCase(TestCase):
    fixtures = ['location.json']

    def test_update_location(self):

        c = Client()
        response = c.post('/tracker/update', {'username' : '5',
                                              'report': 'M20 Uptown', 
                                              'lat': '40.737606', 
                                              'lng' : '-74.006393',
                                              'date' : '2009-04-23T05:06:07Z'})
        assert response.status_code == 200

        response = c.get('/tracker/')
        self.assertTrue('M20 Uptown' in response.content)

        bus = Bus.objects.get(id=5)
        observations = bus.busobservation_set.filter(time=datetime.strptime("2009-04-23T05:06:07Z", '%Y-%m-%dT%H:%M:%SZ'))
        self.assertEqual(len(observations), 1)
        observation = observations[0]
        self.assertAlmostEqual(observation.location.x, -74.006393)
        self.assertAlmostEqual(observation.location.y, 40.737606) 

    def test_estimate(self):

        assert BusObservation.objects.all().count() > 3

        c = Client()

        response = c.get('/tracker/locate', 
                         { 'route_name' : 'M20 Uptown',
                           'lat': '40.766735', 
                           'long' : '-73.983093',
                           'time' : '1239644900',
                           }
                          )
        #there's an estimate for the bus on this day
        self.assertEqual(response.status_code, 200)
        self.assertTrue('2009-04-13' in response.content)

        response = c.get('/tracker/locate', 
                         { 'route_name' : 'M20 Uptown',
                           'lat': '40.766735', 
                           'long' : '-73.983093',
                           'time' : '1239645900',
                           }
                          )
        #there's an estimate for the bus on this day, after the first bus has passed 
        self.assertEqual(response.status_code, 200)
        self.assertTrue('2009-04-13' in response.content)


        response = c.get('/tracker/locate', 
                         { 'route_name' : 'M20 Uptown',
                           'lat': '40.766735', 
                           'long' : '-73.983093',
                           'time' : '1239650000',
                           }
                          )

        #and there's not an estimate for the bus if we ask too late
        self.assertEqual(response.status_code, 200)
        self.assertFalse('2009-04-13' in response.content)

    def test_estimate_geocode(self):

        assert BusObservation.objects.all().count() > 3

        c = Client()

        response = c.get('/tracker/locate_by_address', 
                         { 'route_name' : 'M20 Uptown',
                           'lat': '40.766735', 
                           'long' : '-73.983093',
                           'time' : '1239644900',
                           'address' : "8 Ave and W 56 St",
                           })

        self.assertEqual(response.status_code, 200)
        self.assertTrue('2009-04-13' in response.content)

        #this location is the bus's last seen location; 
        #the time parameter, above, does not eliminate observations
        #of the bus after that time.
        self.assertTrue('W 57 St' in response.content)
        self.assertTrue('8 Ave' in response.content)

    def test_kml(self):
        
        c = Client()

        response = c.get('/tracker/kml', 
                         { 'bus_id' : '2' })


        self.assertEqual(response.status_code, 200)
        self.assertTrue('-74.005859, 40.737423' in response.content)

    def test_estimate_accuracy(self):
        """Test the accuracy of the estimation algorithm.  It uses
        the M6 dataset, a record of two bus trips on the M6 bus.

        Estimates are taken one minute, two minutes, ten minutes, and
        twenty minutes before arrival at each observation.
        """

        intervals =[timedelta(0, x) for x in (60, 120, 600, 1200)]

        #todo: run the M6 route
        #route = Route.objects.get(name="M6 Downtown")
        route = Route.objects.get(name="M20 Uptown")

        for bus in route.bus_set.all():
            observations = list(bus.busobservation_set.all())
            first_observation_time = observations[0].time

            total_diff = 0
            n_samples = 0
            for observation in observations:
                for interval in intervals:
                    estimate_time = observation.time - interval
                    if estimate_time > first_observation_time:
                        estimated_time = bus.estimated_arrival_time(observation.location, estimate_time)
                        if estimated_time:
                            diff = abs((estimated_time - observation.time).seconds)
                            total_diff += diff * diff
                            n_samples += 1

        print "Divergence for this data set: %s" % (total_diff / n_samples)

