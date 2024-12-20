import streamlit as st
import requests
from datetime import datetime, timedelta
import pytz
import plotly.express as px
import pandas as pd
from retry_requests import retry
import openmeteo_requests
import requests_cache

# Constants
HOCHFUEGEN_TZ = pytz.timezone("Europe/Vienna")
WEBCAM_URL = "https://sts001.feratel.co.at/streams/stsstore005/1/05560_676529cf-faccVid.mp4?dcsdesign=WTP_bergfex.at"
APRES_URL = "https://media1.tenor.com/m/q9vlUNHHs1YAAAAC/eddo-bier.gif"
POWDER_URL = "https://i.giphy.com/media/v1.Y2lkPTc5MGI3NjExYnphNWxwMWFrc3p4ejhqcTN0Ymt2eXgxaHdwam9ia2RlaG1qaHJlMyZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/UQJqOcrkNHK7BlJYBo/giphy.gif"
# Dark blue theme colors
DARK_BLUE = 'rgba(129, 203, 199, 0.5)'  # Dark blue with 0.9 opacity
LIGHT_TEXT = '#FFFFFF'  # White text for contrast
GRID_COLOR = 'rgba(255, 255, 255, 0.2)'  # Subtle white grid
CHART_CONFIG = {
    'background_color': DARK_BLUE,
    'font_color': LIGHT_TEXT,
    'grid_color': GRID_COLOR
}

# Helper function to generate next 48-hour dropdown options
def generate_time_options():
    now = datetime.now(HOCHFUEGEN_TZ)
    options = [(now + timedelta(hours=i)).strftime("%d-%m-%Y %H:00") for i in range(48)]
    return options

# Setup the Open-Meteo API client with cache and retry on error
cache_session = requests_cache.CachedSession('.cache', expire_after = -1)
retry_session = retry(cache_session, retries = 5, backoff_factor = 0.2)
openmeteo = openmeteo_requests.Client(session = retry_session)

# Make sure all required weather variables are listed here
# The order of variables in hourly or daily is important to assign them correctly below
url = "https://api.open-meteo.com/v1/forecast"
params = {
    "latitude": 47.26580883196723,
    "longitude": 11.84457426992035,
    'past_hours': 7 * 24,
    'forecast_hours': 0,
    "hourly": ["temperature_2m", "relative_humidity_2m", "dew_point_2m", "precipitation", "rain", "snowfall", "snow_depth", "weather_code", "pressure_msl", "surface_pressure", "cloud_cover", "cloud_cover_low", "cloud_cover_mid", "cloud_cover_high", "et0_fao_evapotranspiration", "vapour_pressure_deficit", "wind_speed_10m", "wind_speed_120m", "wind_direction_10m", "wind_direction_120m", "wind_gusts_10m", "soil_temperature_0cm", "soil_temperature_6cm", "soil_temperature_18cm", "soil_temperature_54cm", "soil_moisture_0_to_1cm", "soil_moisture_1_to_3cm", "soil_moisture_3_to_9cm", "soil_moisture_9_to_27cm", "soil_moisture_27_to_81cm"]
}
responses = openmeteo.weather_api(url, params=params)

# Process first location. Add a for-loop for multiple locations or weather models
response = responses[0]
# Process hourly data. The order of variables needs to be the same as requested.
hourly = response.Hourly()
hourly_temperature = hourly.Variables(0).ValuesAsNumpy()
hourly_snow_depth = hourly.Variables(6).ValuesAsNumpy()

hourly_data = {"date": pd.date_range(
	start = pd.to_datetime(hourly.Time(), unit = "s", utc = True),
	end = pd.to_datetime(hourly.TimeEnd(), unit = "s", utc = True),
	freq = pd.Timedelta(seconds = hourly.Interval()),
	inclusive = "left"
)}

hourly_data["Snow Depth"] = hourly_snow_depth * 100
hourly_data["Temperature"] =hourly_temperature
hourly_dataframe = pd.DataFrame(data = hourly_data)

def fetch_combined_data(snowdepth_url, temperature_url):
    try:
        # Fetch snowfall data
        snowdepth_response = requests.get(snowdepth_url)
        if snowdepth_response.status_code == 200:
            snowdepth_data = snowdepth_response.json()
            snowdepth_first_predict_time = datetime.strptime(snowdepth_data["first_predict_time"], "%Y-%m-%dT%H:%M")
            snowdepth_list = snowdepth_data["snowdepth_prediction"]
            snowdepth_predictions = [i * 100 for i in snowdepth_list]
            snowdepth_dates = [snowdepth_first_predict_time + timedelta(hours=i) for i in range(len(snowdepth_predictions))]
        else:
            print(f"Error: Snowfall API returned status code {snowdepth_response.status_code}")
            return None

        # Fetch temperature data
        temperature_response = requests.get(temperature_url)
        if temperature_response.status_code == 200:
            temperature_data = temperature_response.json()
            temperature_first_predict_time = datetime.strptime(temperature_data["first_predict_time"], "%Y-%m-%dT%H:%M")
            temperature_predictions = temperature_data["temperature_prediction"]
            temperature_dates = [temperature_first_predict_time + timedelta(hours=i) for i in range(len(temperature_predictions))]
        else:
            print(f"Error: Temperature API returned status code {temperature_response.status_code}")
            return None

        # Align start times
        start_time = max(snowdepth_first_predict_time, temperature_first_predict_time)

        # Truncate snow depth data
        snowdepth_start_index = (start_time - snowdepth_first_predict_time).total_seconds() // 3600
        snowdepth_start_index = int(max(0, snowdepth_start_index))  # Ensure index is non-negative
        snowdepth_dates = snowdepth_dates[snowdepth_start_index:]
        snowdepth_predictions = snowdepth_predictions[snowdepth_start_index:]

        # Truncate temperature data
        temperature_start_index = (start_time - temperature_first_predict_time).total_seconds() // 3600
        temperature_start_index = int(max(0, temperature_start_index))  # Ensure index is non-negative
        temperature_dates = temperature_dates[temperature_start_index:]
        temperature_predictions = temperature_predictions[temperature_start_index:]

        # Ensure data alignment and combine into a single DataFrame
        min_length = min(len(snowdepth_dates), len(temperature_dates))
        combined_df = pd.DataFrame({
            "date": snowdepth_dates[:min_length],  # Use the shorter length
            "Snow Depth": snowdepth_predictions[:min_length],
            "Temperature": temperature_predictions[:min_length]
        })
        return combined_df

    except Exception as e:
        print(f"Error: API request failed with exception: {e}")
        return None

def create_forecast_chart(data, value_vars):
    # Melt the data to create a "long format" for multiple y-series
    data_long = data.melt(id_vars='date',
                          value_vars=value_vars,
                          var_name='variable',
                          value_name='value')

    # Create the line chart
    fig = px.line(
        data_long,
        x='date',
        y='value',
        color='variable',  # Different colors for Snow Depth and Temperature
        labels={'value': 'Measurement', 'variable': 'legend'},
    )

    # Update layout for styling
    fig.update_layout(
        xaxis_title=None,
        yaxis_title=None,
        template="plotly_white",
        paper_bgcolor='#373737',
        plot_bgcolor=CHART_CONFIG['background_color'],
        font_color=CHART_CONFIG['font_color'],
        xaxis=dict(
            gridcolor=CHART_CONFIG['grid_color'],
            showgrid=True
        ),
        yaxis=dict(
            gridcolor=CHART_CONFIG['grid_color'],
            showgrid=True
        )
    )
    return fig


# Title and subheader
st.title("Hochfügen Ski Resort Forecast")
st.markdown("##### Get accurate snowfall and temperature forecasts for the next 48 hours.")
st.markdown("##### ")

# Webcam
st.markdown("### Hochfügen Lamarkalm Webcam")
st.markdown(
    f'<iframe src="{WEBCAM_URL}" width="100%" height="400" style="border:0;"></iframe>',
    unsafe_allow_html=True,
)
st.markdown("##### ")

# Dropdown for time selection
st.markdown("### Choose Forecast Time")
time_options = generate_time_options()
selected_time = st.selectbox("Select Date and Time:", time_options, label_visibility='collapsed')
selected_time_dt = datetime.strptime(selected_time, "%d-%m-%Y %H:00")


# Forecast button
if st.button("Get Forecast"):
    st.markdown("##### ")
    # Extract date and hour from selected time
    selected_date, selected_hour = selected_time.split(" ")

    # API endpoints
    snowdepth_api_url = "https://powderalert-demodayversion-884569188278.europe-west1.run.app/predict_snowdepth?lat=47.26580883196723&long=11.84457426992035"
    temperature_api_url = "https://powderalert-demodayversion-884569188278.europe-west1.run.app/predict_temperature?lat=47.26580883196723&long=11.84457426992035"
    windspeed_api_url = "https://powderalert-demodayversion-884569188278.europe-west1.run.app/predict_windspeed?lat=47.26580883196723&long=11.84457426992035"
    col1, col2, col3, = st.columns([1, 1, 1])

    with col1:
        # Temperature API request
        try:
            temperature_response = requests.get(temperature_api_url)
            if temperature_response.status_code == 200:
                temperature_data = temperature_response.json()
                temperature_first_predict_time = datetime.strptime(temperature_data["first_predict_time"], "%Y-%m-%dT%H:%M")
                temperature_predictions = temperature_data.get("temperature_prediction", [])

                # Generate the list of prediction times
                temperature_dates = [temperature_first_predict_time + timedelta(hours=i) for i in range(len(temperature_predictions))]

                # Find the prediction matching the selected time
                if selected_time_dt in temperature_dates:
                    temperature_index = temperature_dates.index(selected_time_dt)
                    selected_temperature = temperature_predictions[temperature_index]
                else:
                    selected_temperature = "N/A"

                # Display temperature predictions
                st.markdown("#### Temperature")
                temperature = st.metric(
                                        label="Predicted Temperature (°C)",
                                        label_visibility='collapsed',
                                        value=f"{round(selected_temperature)} °C" if selected_temperature != "N/A" else selected_temperature
                                        )
            else:
                selected_temperature = "Error retrieving data"
        except Exception as e:
            f"Error: {e}"
    with col2:
    # Snow depth API request
        try:
            snowdepth_response = requests.get(snowdepth_api_url)
            if snowdepth_response.status_code == 200:
                snowdepth_data = snowdepth_response.json()
                snowdepth_first_predict_time = datetime.strptime(snowdepth_data["first_predict_time"], "%Y-%m-%dT%H:%M")
                snowdepth_predictions = snowdepth_data.get("snowdepth_prediction", [])

                # Generate the list of prediction times
                snowdepth_dates = [snowdepth_first_predict_time + timedelta(hours=i) for i in range(len(snowdepth_predictions))]

                # Find the prediction matching the selected time
                if selected_time_dt in snowdepth_dates:
                    snowdepth_index = snowdepth_dates.index(selected_time_dt)
                    selected_snowdepth = snowdepth_predictions[snowdepth_index] * 100

                # Display snowdepth predictions
                st.markdown("#### Snow Depth")
                snowdepth = st.metric(
                    label="Predicted Snow Depth (cm)",
                    value=f"{round(selected_snowdepth)} cm" if selected_snowdepth != "N/A" else selected_snowdepth,
                    label_visibility='collapsed'
                )
            else:
                "Error retrieving snowfall data."
        except Exception as e:
            f"Error: {e}"
    with col3:
        # Wind speed API request
        try:
            windspeed_response = requests.get(windspeed_api_url)
            if temperature_response.status_code == 200:
                windspeed_data = windspeed_response.json()
                windspeed_first_predict_time = datetime.strptime(windspeed_data["first_predict_time"], "%Y-%m-%dT%H:%M")
                windspeed_predictions = windspeed_data.get("windspeed_prediction", [])

                # Generate the list of prediction times
                windspeed_dates = [windspeed_first_predict_time + timedelta(hours=i) for i in range(len(windspeed_predictions))]

                # Find the prediction matching the selected time
                if selected_time_dt in windspeed_dates:
                    windspeed_index = windspeed_dates.index(selected_time_dt)
                    selected_windspeed = windspeed_predictions[windspeed_index]

                # Display wind speed predictions
                st.markdown("#### Wind Speed")
                windspeed = st.metric(
                    label="Predicted Temperature (°C)",
                    label_visibility='collapsed',
                    value=f"{round(selected_windspeed)} km/h" if selected_windspeed != "N/A" else selected_windspeed
                )
            else:
                "Error retrieving temperature data."
        except Exception as e:
            f"Error: {e}"
    st.markdown("#### ")
    if float(selected_temperature) < 0:
        st.markdown("## Put that pint down and go home !")
        st.markdown("##### ")
        st.image(POWDER_URL)
    elif float(selected_temperature) >= 0:
        st.markdown("## Get that pint down your neck !")
        st.markdown("##### ")
        st.image(APRES_URL)

    # Fetch the combined data
    combined_df = fetch_combined_data(snowdepth_api_url, temperature_api_url)
    #st.write(combined_df)
   # Display forecast chart
    st.markdown("##### ")
    st.markdown("### Next 48 hours snow depth (cm) and temperature (°C) forecast")
    st.plotly_chart(
        create_forecast_chart(combined_df, value_vars=["Snow Depth", "Temperature"]),
        use_container_width=True
        )

# Display forecast chart
st.markdown("##### ")
st.markdown("### Previous 7 days snow depth (cm) and temperature (°C)")
st.plotly_chart(
    create_forecast_chart(hourly_dataframe, value_vars=['Snow Depth', 'Temperature']),
    use_container_width=True
)

# Styling for the wintery blue theme
st.markdown(
    """
    <style>
    .stApp {
        background: #373737;
        color: #81CBC7;
    }
    .stMetricLabel {
        font-size: 1.2rem;
        font-weight: bold;
    }
    iframe {
        border-radius: 16px; /* Rounded corners for iframe */
    }
    /* Custom selectbox size */
    div[data-baseweb="select"] {
        width: 200px !important;
    }
    /* Selected value area */
    div[data-baseweb="select"] > div {
        background-color: #373737 !important; /* Background color */
        color: #81CBC7 !important; /* Font color */
        border: 1px solid #81CBC7 !important; /* Border color */
        border-radius: 8px !important; /* Rounded corners */
        font-weight: normal;
    }
    /* Dropdown list (menu) */
    ul[role="listbox"] {
        background-color: #2E3B4E !important; /* Background color for dropdown */
        border: 2px solid #F5AF80 !important; /* Border color for dropdown */
    }
    /* Dropdown list items */
    ul[role="listbox"] > li {
        background-color: #373737 !important; /* Item background */
        color: #81CBC7 !important; /* Item font color */
        font-weight: bold;
        padding: 8px;
    }
    /* Hover effect for dropdown items */
    ul[role="listbox"] > li:hover {
        background-color: #81CBC7 !important; /* Hover background */
        color: #373737 !important; /* Hover text color */
    }
    /* Selected dropdown option */
    ul[role="listbox"] > li[aria-selected="true"] {
        background-color: #81CBC7 !important; /* Selected background color */
        color: #373737 !important; /* Selected font color */
    }
    /* Customize button */
    div.stButton > button {
        background-color: #373737 !important; /* Button background color */
        color: #81CBC7 !important; /* Button text color */
        border-radius: 8px; /* Rounded corners for the button */
        border-color: #81CBC7; /* Remove button border */
        font-weight: bold;
        font-size: 16px;
    }
        /* Button hover effect */
    div.stButton > button:hover {
        background-color: #81CBC7 !important; /* Background color on hover */
        color: #373737 !important; /* Text color on hover */
        border: 2px solid #81CBC7 !important; /* Border color on hover */
    }
    </style>
    """,
    unsafe_allow_html=True,
)
