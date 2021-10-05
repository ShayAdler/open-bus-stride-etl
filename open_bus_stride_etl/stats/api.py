import datetime

import pytz
from ruamel import yaml
from sqlalchemy import desc, func, and_

from open_bus_stride_db.db import session_decorator, Session  # provides type hinting for session_decorator
from open_bus_stride_db.model.siri_snapshot import SiriSnapshot, SiriSnapshotEtlStatusEnum
from open_bus_stride_db.model.vehicle_location import VehicleLocation
from open_bus_stride_db.model.ride import Ride
from open_bus_stride_db.model.route import Route
from open_bus_stride_db.model.route_stop import RouteStop
from open_bus_stride_db.model.stop import Stop

from ..common import parse_siri_snapshot_id


@session_decorator
def siri_snapshots_iterator(session, limit):
    for siri_snapshot in session.query(SiriSnapshot).order_by(desc(SiriSnapshot.etl_start_time))[:limit]:
        etl_status: SiriSnapshotEtlStatusEnum = siri_snapshot.etl_status
        yield {
            'snapshot_id': siri_snapshot.snapshot_id,
            'etl_status': etl_status.value,
            'etl_start_time': siri_snapshot.etl_start_time,
            'etl_end_time': siri_snapshot.etl_end_time,
            'error': siri_snapshot.error,
            'num_successful_parse_vehicle_locations': siri_snapshot.num_successful_parse_vehicle_locations,
            'num_failed_parse_vehicle_locations': siri_snapshot.num_failed_parse_vehicle_locations,
            'vehicle_locations': len(siri_snapshot.vehicle_locations),
        }


@session_decorator
def last_day_stats_iterator(session: Session, limit=5, from_=None):
    if not from_:
        now = datetime.datetime.now()
        from_ = pytz.timezone('israel').localize(datetime.datetime(now.year, now.month, now.day))
    for i in range(limit):
        date = from_ - datetime.timedelta(days=i)
        datetime_from = pytz.timezone('israel').localize(datetime.datetime(date.year, date.month, date.day, 0, 0))
        datetime_to = datetime_from + datetime.timedelta(days=1)
        session.query(RouteStop).join(Route)
        yield {
            'date': date,
            'siri_snapshot': {
                'by_etl_started': session.query(SiriSnapshot).filter(
                    SiriSnapshot.etl_start_time <= datetime_to, SiriSnapshot.etl_start_time >= datetime_from
                ).count(),
                'by_snapshot_id': session.query(SiriSnapshot).filter(
                    SiriSnapshot.snapshot_id.like(datetime_from.strftime('%Y/%m/%d/') + '%')
                ).count()
            },
            'vehicle_location': {
                'by_snapshot_id': session.query(VehicleLocation).filter(
                    VehicleLocation.siri_snapshot.has(SiriSnapshot.snapshot_id.like(datetime_from.strftime('%Y/%m/%d/') + '%'))
                ).count(),
            },
            'ride': {
                'is_from_gtfs': session.query(Ride).filter(
                    Ride.scheduled_start_time <= datetime_to, Ride.scheduled_start_time >= datetime_from,
                    Ride.is_from_gtfs == True
                ).count(),
                'not_from_gtfs': session.query(Ride).filter(
                    Ride.scheduled_start_time <= datetime_to, Ride.scheduled_start_time >= datetime_from,
                    Ride.is_from_gtfs != True
                ).count(),
            },
            'route': {
                'by_rides_is_from_gtfs': session.query(Route).filter(
                    Route.rides.any(and_(Ride.scheduled_start_time <= datetime_to, Ride.scheduled_start_time >= datetime_from)),
                    Route.is_from_gtfs == True
                ).count(),
                'by_rides_not_from_gtfs': session.query(Route).filter(
                    Route.rides.any(and_(Ride.scheduled_start_time <= datetime_to, Ride.scheduled_start_time >= datetime_from)),
                    Route.is_from_gtfs != True
                ).count(),
            },
            'route_stop': {
                'by_route_is_from_gtfs': session.query(RouteStop).join(Route).join(Ride).filter(
                    Ride.scheduled_start_time <= datetime_to, Ride.scheduled_start_time >= datetime_from,
                    Route.is_from_gtfs == True
                ).count(),
                'by_route_not_from_gtfs': session.query(RouteStop).join(Route).join(Ride).filter(
                    Ride.scheduled_start_time <= datetime_to, Ride.scheduled_start_time >= datetime_from,
                    Route.is_from_gtfs != True
                ).count(),
            },
            'stop': {
                'by_route_stop_is_from_gtfs': session.query(Stop).join(RouteStop).join(Route).join(Ride).filter(
                    Ride.scheduled_start_time <= datetime_to, Ride.scheduled_start_time >= datetime_from,
                    Route.is_from_gtfs == True
                ).count(),
                'by_route_stop_not_from_gtfs': session.query(Stop).join(RouteStop).join(Route).join(Ride).filter(
                    Ride.scheduled_start_time <= datetime_to, Ride.scheduled_start_time >= datetime_from,
                    Route.is_from_gtfs != True
                ).count(),
            }
        }


@session_decorator
def collect(session, latest_siri_snapshots_limit=10, last_days_limit=5, last_days_from=None, print_results=False, validate=False):
    res = {
        'num_siri_snapshots': session.query(SiriSnapshot).count(),
        'siri_snapshots_iterator': siri_snapshots_iterator(limit=latest_siri_snapshots_limit),
        'last_day_stats_iterator': last_day_stats_iterator(limit=last_days_limit, from_=last_days_from)
    }
    if print_results:
        print('total_siri_snapshots: {}'.format(res['num_siri_snapshots']))
        print('last_days:  # last {} days'.format(last_days_limit))
        for last_day_stats in res['last_day_stats_iterator']:
            print(yaml.safe_dump([last_day_stats]).strip())
        print('latest_siri_snapshots:  # latest {} siri snapshots'.format(latest_siri_snapshots_limit))
        latest_snapshot_datetime = None
        for siri_snapshot in res['siri_snapshots_iterator']:
            snapshot_datetime = parse_siri_snapshot_id(siri_snapshot['snapshot_id'])
            if not latest_snapshot_datetime or latest_snapshot_datetime < snapshot_datetime:
                latest_snapshot_datetime = snapshot_datetime
            print(yaml.safe_dump([siri_snapshot]).strip())
        if validate:
            is_valid = True
            if not latest_snapshot_datetime:
                print("VALIDATION ERROR: no latest snapshot")
                is_valid = False
            elif latest_snapshot_datetime < (datetime.datetime.now(pytz.UTC) - datetime.timedelta(hours=1)):
                print("VALIDATION ERROR: latest snapshot is older than 1 hour: {}".format(latest_snapshot_datetime))
                is_valid = False
            else:
                print("VALIDATION SUCCESS: latest snapshot is not older then 1 hour: {}".format(latest_snapshot_datetime))
            return is_valid
        else:
            return True
    else:
        assert not validate, 'validate is not supported if print_results is False'
        return res
