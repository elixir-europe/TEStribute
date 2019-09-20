"""
Functions that interact with external services.
"""
from collections import defaultdict
import logging
import socket
from typing import (Dict, Iterable, Mapping, Optional)

from bravado.exception import HTTPNotFound
import drs_client
from geopy.distance import geodesic
from ip2geotools.databases.noncommercial import DbIpCity
from ip2geotools.errors import InvalidRequestError
from requests.exceptions import ConnectionError, HTTPError, MissingSchema
from simplejson.errors import JSONDecodeError
import tes_client
from urllib.parse import urlparse

from TEStribute.errors import ResourceUnavailableError
from TEStribute.models import (DrsObject, ResourceRequirements)

logger = logging.getLogger("TEStribute")

def fetch_drs_objects_metadata(
    drs_uris: Iterable[str],
    drs_ids: Iterable[str],
    jwt: Optional[str] = None,
    check_results: bool = True,
    timeout: float = 3,
) -> Dict[str, Dict[str, DrsObject]]:
    """
    Returns access information for an iterable object of DRS identifiers
    available at the specified DRS instances.

    :param drs_uris: List (or other iterable object) of root URIs of DRS
            instances.
    :param drs_ids: List (or other iterable object) of globally unique DRS
            identifiers.
    :param check_results: Check whether every object is available at least at
            one DRS instance.
    :param timeout: Time (in seconds) after which an unsuccessful connection
            attempt to the DRS should be terminated.

    :return: Dict of dicts of DRS object identifers in `drs_ids` (keys outer
            dictionary) and DRS root URIs in `drs_uris` (keys inner
            dictionaries) and a dictionary containing the information defined by
            the `Object` model of the DRS specification (values inner
            dictionaries). The inner dictionary for any given DRS object will
            only contain values for DRS instances for which the object is
            available.
    """
    # Initialize results container
    result_dict = defaultdict(dict)

    # Iterate over DRS instances
    for drs_uri in drs_uris:

        # Fetch object metadata at current DRS instance
        metadata = _fetch_drs_objects_metadata(
            uri=drs_uri,
            *drs_ids,
            timeout=timeout,
        )

        # Add metadata for each object to results container, if available
        if metadata:
            for drs_id in metadata:
                result_dict[drs_id].update({
                    drs_uri: metadata[drs_id]
                })

        # Check whether any object is unavailable
        if check_results:

            # Check availability of objects
            for drs_id in drs_ids:
                if drs_id not in result_dict:
                    raise ResourceUnavailableError(
                        f"Object '{drs_id}' is not available at any of the " \
                        f"specified DRS instances."
                    )

        # Return results
    return result_dict


def _fetch_drs_objects_metadata(
    uri: str,
    *ids: str,
    timeout: float = 3,
) -> Dict[str, DrsObject]:
    """
    Returns access information for an iterable object of DRS identifiers
    available at the specified DRS instance.

    :param uri: Root URI of DRS instance.
    :param ids: List (or other iterable object) of globally unique DRS
            identifiers.
    :param timeout: Time (in seconds) after which an unsuccessful connection
            attempt to the DRS should be terminated. Currently not implemented.

    :return: Dict of DRS object identifers in `ids` (keys) and a dictionary
            containing the information defined by the `Object` model of the DRS
            specification (values). Objects that are unavailable at the DRS
            instances will be omitted from the dictionary. In case of a
            connection error at any point, an empty dictionary is returned.
    """
    # Initialize results container
    objects_metadata: Dict[str, DrsObject] = {}

    # Establish connection with DRS; handle exceptions
    try:
        client = drs_client.Client(uri)
    except TimeoutError:
        logger.warning(
            f"DRS unavailable: connection attempt to DRS '{uri}' timed out."
        )
        return {}
    except (
        ConnectionError,
        HTTPError,
        HTTPNotFound,
        JSONDecodeError,
        MissingSchema,
    ):
        logger.warning(
            f"DRS unavailable: the provided URI '{uri}' could not be " \
            f"resolved."
        )
        return {}

    # Fetch metadata for every object; handle exceptions
    for drs_id in ids:
        # TODO: Cross-check object checksums, die if differ
        # TODO: Cross-check object sizes, die if differ
        try:
            objects_metadata[drs_id] = client.getObject(
                drs_id
            )._as_dict()
        except HTTPNotFound:
            logger.debug(
                f"File '{drs_id}' is not available on DRS '{uri}'."
            )
            continue
        except TimeoutError:
            logger.warning(
                f"DRS unavailable: connection attempt to DRS '{uri}' timed " \
                f"out."
            )
            continue

    # Return object metadata
    return objects_metadata


def fetch_tes_task_info(
    tes_uris: Iterable[str],
    resource_requirements: ResourceRequirements,
    check_results: bool = True,
    timeout: float = 3,
) -> Dict:
    """
    Given a set of resource requirements, returns queue time, cost estimates and
    related parameters at the specified TES instances.

    :param tes_uris: List (or other iterable object) of root URIs of TES
            instances.
    :param resource_requirements: Dict of compute resource requirements of the
            form defined in the `tesResources` model of the modified TES
            speficications in the `mock-TES` repository at:
            https://github.com/elixir-europe/mock-TES/blob/master/mock_tes/specs/schema.task_execution_service.d55bf88.openapi.modified.yaml
    :param check_results: Check whether the resulting dictionary contains data
            for at least one TES instance.
    :param timeout: Time (in seconds) after which an unsuccessful connection
            attempt to the DRS should be terminated.

    :return: Dict of TES URIs in `tes_uris` (keys) and a dictionary containing
             queue time and cost estimates/rates (values) as defined in the
            `tesTaskInfo` model of the modified TES specifications in the
            `mock-TES` repository: https://github.com/elixir-europe/mock-TES
    """
    # Initialize results container
    result_dict = {}

    # Iterate over TES instances
    for uri in tes_uris:

        # Fetch task info at current TES instance
        task_info = _fetch_tes_task_info(
            uri=uri,
            resource_requirements=resource_requirements,
            timeout=timeout,
        )

        # If available, add task info to results container
        if task_info:
            result_dict[uri] = task_info
        
    # Check whether at least one TES instance provided task info
    if check_results and not result_dict:
        raise ResourceUnavailableError(
            "None of the specified TES instances provided any task info."
        )
    
    # Return results
    return result_dict


def _fetch_tes_task_info(
    uri: str,
    resource_requirements: ResourceRequirements,
    timeout: float = 3,
) -> Dict:
    """
    Given a set of resource requirements, returns queue time, cost estimates and
    related parameters at the specified TES instance.

    :param uri: Root URI of TES instance.
    :param resource_requirements: Dict of compute resource requirements of the
            form defined in the `tesResources` model of the modified TES
            speficications in the `mock-TES` repository at:
            https://github.com/elixir-europe/mock-TES/blob/master/mock_tes/specs/schema.task_execution_service.d55bf88.openapi.modified.yaml
    :param timeout: Time (in seconds) after which an unsuccessful connection
            attempt to the DRS should be terminated. Currently not implemented.

    :return: Dict of queue time and cost estimates/rates as defined in the
            `tesTaskInfo` model of the modified TES specifications in the
            `mock-TES` repository: https://github.com/elixir-europe/mock-TES

    """
    # Establish connection with TES; handle exceptions
    try:
        client = tes_client.Client(uri)
    except TimeoutError:
        logger.warning(
            f"TES unavailable: connection attempt to '{uri}' timed out."
        )
        return {}
    except (ConnectionError, JSONDecodeError, HTTPNotFound, MissingSchema):
        logger.warning(
            f"TES unavailable: the provided URI '{uri}' could not be " \
            f"resolved."
        )
        return {}

    # Fetch task info; handle exceptions
    try:
        return client.getTaskInfo(
            timeout=timeout,
            **resource_requirements,
        )._as_dict()
    except TimeoutError:
        logger.warning(
            f"Connection attempt to TES {uri} timed out. TES " \
            f"unavailable. Skipped."
        )
        return {}


def estimate_distances(
    combinations: Mapping,
) -> Dict:
    """
    """
    return {}


def ip_distance(
    url1: str,
    url2: str
) -> Dict:
    """
    :param ip1: string ip/url
    :param ip2: string ip/url

    :return: a dict containing the locations of both input addresses &
    the physical distance between them in km's
    """
    # Convert domains to IPs
    try:
        ip1 = socket.gethostbyname(urlparse(url1).netloc)
        ip2 = socket.gethostbyname(urlparse(url2).netloc)
    except socket.gaierror:
        raise

    # Locate IPs
    try:
        ip1_loc = DbIpCity.get(ip1, api_key="free")
        ip2_loc = DbIpCity.get(ip2, api_key="free")
    except InvalidRequestError:
        raise

    # Prepare, log and return results
    ret = {
        "source": {
            "city": ip1_loc.city,
            "region": ip1_loc.region,
            "country": ip1_loc.country
        },
        "destination": {
            "city": ip2_loc.city,
            "region": ip2_loc.region,
            "country": ip2_loc.country
        },
        "distance": geodesic(
            (ip1_loc.latitude, ip1_loc.longitude),
            (ip2_loc.latitude, ip2_loc.longitude),
        ).km,
    }
    logger.debug(
        f"Distance calculation between {url1} and {url2}: {ret}"
    )
    return ret