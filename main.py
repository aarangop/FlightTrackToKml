import os
from datetime import datetime, time

import pandas as pd
from lxml import etree

kml_ext_namespace = "http://www.google.com/kml/ext/2.2"

feet2metre = 0.3048
metre2feet = 1 / feet2metre

track_style_str = style = """
    <Styles>
        <StyleMap id="msn_track">
            <Pair>
                <key>normal</key>
                <styleUrl>#sn_track</styleUrl>
            </Pair>
            <Pair>
                <key>highlight</key>
                <styleUrl>#sh_track</styleUrl>
            </Pair>
        </StyleMap>
        <Style id="sh_track">
            <IconStyle>
                <scale>1.4</scale>
                <Icon>
                    <href>http://maps.google.com/mapfiles/kml/shapes/track.png</href>
                </Icon>
                <hotSpot x="32" y="32" xunits="pixels" yunits="pixels"/>
            </IconStyle>
            <BalloonStyle>
            </BalloonStyle>
            <ListStyle>
            </ListStyle>
            <LineStyle>
                <color>ffff55ff</color>
            </LineStyle>
        </Style>
        <Style id="sn_track">
            <IconStyle>
                <scale>1.2</scale>
                <Icon>
                    <href>http://maps.google.com/mapfiles/kml/shapes/track.png</href>
                </Icon>
                <hotSpot x="32" y="1" xunits="pixels" yunits="pixels"/>
            </IconStyle>
            <BalloonStyle>
            </BalloonStyle>
            <ListStyle>
            </ListStyle>
            <LineStyle>
                <color>ffff55ff</color>
            </LineStyle>
        </Style>
	</Styles>
    """


def get_trajectory_dataframe_from_csv_file(input_filename):
    trajectory_original = pd.read_excel(input_filename, skiprows=[1])

    # Rename columns
    names = {
        "Timestamp": "timestamp",
        "A/C LATITUDE": "latitude",
        "A/C LONGITUDE": "longitude",
        "ABSOLUTE HEIGHT ABOVE SEALEVEL": "altitude",
        "CALIBRATED AIRSPEED": "calibrated_airspeed",
        "GROUND SPEED": "ground_speed",
        "TOTAL A/C VERTICAL SPEED": "vertical_speed",
        "TRUE TRACK ANGLE": "track"
    }
    trajectory = trajectory_original[names.keys()].rename(columns=names)

    # Calculate the elapsed time from the timestamps
    trajectory["elapsed_seconds"] = trajectory["timestamp"] - trajectory["timestamp"].iloc[0]
    # Convert elapsed seconds to timedelta
    trajectory["elapsed_seconds"] = pd.to_timedelta(trajectory["elapsed_seconds"], unit="seconds")
    # Calculate an absolute time based on the start of today.
    reference_datetime = datetime.combine(datetime.now().date(), time.min)
    # Add the elapsed seconds to the reference date to obtain an absolute date for each datum
    trajectory["datetime"] = reference_datetime + trajectory["elapsed_seconds"]
    # Create a column with the formatted date as string
    # Reference format 2022-02-28T01:00:37.950000+01:00
    trajectory["datetime_str"] = trajectory["datetime"].dt.strftime("%Y-%m-%dT%H:%M:%S+00:00")
    return trajectory


def get_kml_document_skeleton(document_name: str):
    # Create a new xml document
    root = etree.Element("kml")

    # Add a root document
    root_document = etree.SubElement(root, "Document")
    root_document_name = etree.SubElement(root_document, "name")

    root_document_name.text = document_name

    return root


def save_file(output_file: str, xml_root):
    tree = etree.ElementTree(xml_root)
    tree.write(output_file, xml_declaration=True, encoding="utf-8", pretty_print=True)


def new_point(element, latitude, longitude, altitude, altitude_mode="absolute"):
    point_element = etree.SubElement(element, "Point")
    point_coordinates = etree.SubElement(point_element, "coordinates")
    point_coordinates.text = f"{longitude},{latitude},{altitude}"
    set_altitude_mode(point_element, "absolute")
    return point_element


def new_placemark(
        element,
        name,
        description,
        latitude=None,
        longitude=None,
        altitude=None,
        altitude_mode="absolute"
):
    placemark_element = etree.SubElement(element, "Placemark")
    placemark_element_name = etree.SubElement(placemark_element, "name")
    placemark_element_name.text = name
    placemark_element_description = etree.SubElement(placemark_element, "description")
    placemark_element_description.text = description

    if not latitude or not longitude or not altitude:
        return placemark_element

    new_point(placemark_element, latitude, longitude, altitude, altitude_mode)

    return placemark_element


def add_track_element(track, *columns):
    (timestamp, latitude, longitude, altitude, calibrated_airspeed, ground_speed, vertical_speed, track_heading,
     elapsed_seconds, _, datetime_str) = columns
    when_tag = etree.SubElement(track, "when")
    when_tag.text = datetime_str
    coordinate_tag = etree.SubElement(track, f"{{{kml_ext_namespace}}}coord")
    coordinate_tag.text = f"{longitude} {latitude} {altitude}"


def new_folder(elem, name, visible=True):
    folder = etree.SubElement(elem, "Folder")
    folder_name = etree.SubElement(folder, "name")
    folder_name.text = name
    folder_visibility = etree.SubElement(elem, "visibility")
    folder_visibility.text = "1" if visible else "0"
    return folder


def set_altitude_mode(elem, altitude_mode="absolute"):
    if elem.find("altitude_mode"):
        elem.find("altitude_mode").text = altitude_mode
        return elem

    altitude_mode_element = etree.SubElement(elem, "altitudeMode")
    altitude_mode_element.text = altitude_mode


def get_short_coordinates_str(latitude, longitude):
    hemisphere = "N" if latitude > 0 else "S"
    latitude = abs(latitude)
    east_west = "E" if longitude > 0 else "W"
    longitude = abs(longitude)
    return f"{latitude:.4f}{hemisphere},{longitude:.4f}{east_west}"


def track_info_placemark(elem, *columns):
    (timestamp, latitude, longitude, altitude, calibrated_airspeed, ground_speed, vertical_speed, track_heading,
     elapsed_seconds, _, datetime_str) = columns

    description = f"Altitude above MSL={altitude * metre2feet:.0f} ft\n," \
                  f"CAS={calibrated_airspeed:.0f} kts,\n" \
                  f"Ground Speed={ground_speed:.0f} kts,\n" \
                  f"Vertical Speed={vertical_speed * 60:.0f} ft/m, \n" \
                  f"Track={track_heading:.1f} degrees"

    placemark = new_placemark(elem,
                              f"{get_short_coordinates_str(latitude, longitude)}@{elapsed_seconds.seconds:.0f} seconds",
                              description=description,
                              latitude=latitude,
                              longitude=longitude,
                              altitude=altitude)
    return placemark


def create_kml_file_from_csv(input_filename: str, output_filename: str):
    trajectory = get_trajectory_dataframe_from_csv_file(input_filename)
    trajectory["altitude"] *= feet2metre

    trajectory_name = os.path.splitext(os.path.basename(input_filename))[0]

    # Create a new xml document
    # Define namespaces
    namespace_map = {
        "gx": "http://www.google.com/kml/ext/2.2",
        None: "http://www.opengis.net/kml/2.2"
    }

    root = etree.Element("kml", nsmap=namespace_map)
    # Add a root document
    root_document = etree.SubElement(root, "Document")
    root_document_name = etree.SubElement(root_document, "name")

    root_document_name.text = trajectory_name
    # Add shared styles
    style_xml = etree.fromstring(track_style_str)
    styles = style_xml.findall("Style")
    for style_element in styles:
        root_document.append(style_element)
    style_map = style_xml.find("StyleMap")
    root_document.append(style_map)

    # Get the start and end points
    start_point_coordinates = trajectory[["longitude", "latitude", "altitude"]].iloc[0].tolist()

    # Add a LookAt element with timespan and coordinates.
    look_at = etree.SubElement(root_document, "LookAt")
    # Add a timespan element
    timespan_elem = etree.SubElement(look_at, f"{{{kml_ext_namespace}}}TimeSpan")
    timespan_begin = etree.SubElement(timespan_elem, "begin")
    timespan_begin.text = trajectory["datetime_str"].iloc[0]
    timespan_end = etree.SubElement(timespan_elem, "end")
    timespan_end.text = trajectory["datetime_str"].iloc[-1]
    # Add coordinates to look at
    look_at_longitude = etree.SubElement(look_at, "longitude")
    look_at_longitude.text = str(start_point_coordinates[0])
    look_at_latitude = etree.SubElement(look_at, "latitude")
    look_at_latitude.text = str(start_point_coordinates[1])
    look_at_altitude = etree.SubElement(look_at, "altitude")
    look_at_altitude.text = str(5000)
    # Add a tilt angle
    look_at_tilt = etree.SubElement(look_at, "tilt")
    look_at_tilt.text = str(70)
    # Set altitude mode
    set_altitude_mode(look_at, "absolute")

    # Add a placemark for the track animation
    trajectory_4d_placemark = new_placemark(root_document, "4D Trajectory", "4D Trajectory")
    track = etree.SubElement(trajectory_4d_placemark, f"{{{kml_ext_namespace}}}Track")
    track_style_url = etree.SubElement(trajectory_4d_placemark, "styleUrl")
    track_style_url.text = "#msn_track"
    set_altitude_mode(track, "absolute")

    # Add placemarks for start and end
    new_placemark(root_document, "Start", f"Start of recording at {trajectory['datetime_str'].iloc[0]}",
                  latitude=str(trajectory["latitude"].iloc[0]),
                  longitude=str(trajectory["longitude"].iloc[0]),
                  altitude=str(trajectory["altitude"].iloc[0]),
                  altitude_mode="absolute")

    new_placemark(
        root_document, "End",
        f"End of recording at {trajectory['datetime_str'].iloc[-1]}, \n"
        f"duration: {trajectory['elapsed_seconds'].iloc[-1]}",
        latitude=str(trajectory["latitude"].iloc[-1]),
        longitude=str(trajectory["longitude"].iloc[-1]),
        altitude=str(trajectory["altitude"].iloc[-1]),
        altitude_mode="absolute"
    )

    # Add the 4D coordinates to the track
    [add_track_element(track, *columns) for columns in trajectory.to_numpy()]

    trajectory_3d_placemark = new_placemark(root_document, "3D Trajectory", "3D geometry of recorded trajectory.")
    line_string = etree.SubElement(trajectory_3d_placemark, "LineString")
    extrude = etree.SubElement(line_string, "extrude")
    extrude.text = str(1)
    set_altitude_mode(line_string, "absolute")

    # Get the coordinates
    coordinates_4d = list(
        trajectory[["longitude", "latitude", "altitude", "datetime_str"]].itertuples(index=False, name=None))
    coordinates_tag = etree.SubElement(line_string, "coordinates")
    coordinates_elems = [f"{latitude},{longitude},{altitude}" for latitude, longitude, altitude, _ in coordinates_4d]
    coordinates_tag.text = " ".join(coordinates_elems)

    # Add extra placemarks with further information.
    details_folder = new_folder(root_document, "Details", visible=False)
    [track_info_placemark(details_folder, *columns) for columns in trajectory.to_numpy()]

    save_file(output_filename, root)

    return root


if __name__ == '__main__':

    for dirname, __, filenames in os.walk("./data"):
        for filename in filenames:
            if os.path.isdir(filename):
                continue
            if os.path.splitext(filename)[1] != ".xlsx":
                continue
            input_filename = os.path.join(dirname, filename)
            trajectory_name_full = os.path.basename(input_filename)
            trajectory_name = os.path.splitext(trajectory_name_full)[0]
            output_dir = dirname
            output_filename = os.path.join(output_dir, f"{trajectory_name}.kml")

            xml = create_kml_file_from_csv(input_filename, output_filename)

            print(f"Saved trajectory in kml file '{output_filename}'")
