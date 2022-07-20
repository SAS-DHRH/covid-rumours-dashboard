import streamlit as st
import pandas as pd
import altair as alt
from datetime import datetime
from time import perf_counter

@st.cache(persist=True, ttl=60*60)
def load_dataframe(filepath, compression:str = 'infer'):
    '''
    Load csv into pandas dataframe.
    @filepath: Path to a csv file as string
    @compression: As per pandas API doc for read_csv (https://pandas.pydata.org/pandas-docs/stable/reference/api/pandas.read_csv.html)
    '''

    dateindex = 'created_at'

    df = pd.read_csv(filepath, compression=compression, index_col=dateindex, parse_dates=True)
    # Standardise dates to timezone naive
    df = df.tz_localize(None)
    # Standardize time interval to day
    df = df.resample('D').sum().sort_index()
    # Remove data that fall outside Twitter's lifetime
    df = df[(df.index >= '2006-03-01')]
    # Remove time portion of DateTime index
    #df.index = df.index.date

    return df

def load_css(file, type='local'):
    '''
    A hacky workaround for injecting css into Streamlit.
    '''

    if type == 'remote':
        st.markdown(f'<link href="{file}" rel="stylesheet">', unsafe_allow_html=True)
    else:
        with open(file) as f:
            st.markdown(f'<style>{f.read()}</style>', unsafe_allow_html=True)


######################################
## Page layout and library setup
######################################
st.set_page_config(layout="wide")
load_css("assets/css/dashboard.css")


######################################
## Sidebar (dashboard settings)
######################################

with st.sidebar:

    st.title('Covid Rumours in Historical Context')

    data_load_state = st.text('Loading data... (may take 30secs)')
    start = perf_counter()

    tweetdata = load_dataframe('data/stats/tweets-daily.csv')
    retweetdata = load_dataframe('data/stats/tweets-retweeted-daily.csv')
    userdata = load_dataframe('data/stats/users-daily.csv')

    st.session_state.loadtime = perf_counter() - start
    data_load_state.text("Data cached! (took {:.2f}s to load)".format(st.session_state.loadtime))

    with st.form(key='metrics_settings'):

        with st.expander("Date range", expanded=True):

            data_range = {
                'min': [
                    tweetdata.index.min(),
                    retweetdata.index.min(),
                    userdata.index.min()
                ],
                'max': [
                    tweetdata.index.max(),
                    retweetdata.index.max(),
                    userdata.index.max()
                ]
            }

            data_range_start = st.date_input(
                label = 'From (YYYY/MM/DD)',
                value = tweetdata.index.min(),
                min_value = min(data_range['min']),
                max_value = max(data_range['max'])
            )

            data_range_end = st.date_input(
                label = 'To (YYYY/MM/DD)',
                value = tweetdata.index.max(),
                min_value = min(data_range['min']),
                max_value = max(data_range['max'])
            )

        st.form_submit_button('Update')


######################################
## Data
######################################

selected_date_start = data_range_start.strftime('%Y-%m-%d')
selected_date_end = data_range_end.strftime('%Y-%m-%d')

if data_range_start <= data_range_end:
    selected_tweetdata = tweetdata.loc[data_range_start:data_range_end]
    selected_retweetdata = retweetdata.loc[data_range_start:data_range_end]
    selected_userdata = userdata.loc[data_range_start:data_range_end]


######################################
## Content
######################################

st.title('About the data')
st.markdown(
'In total, the corpus contains almost 2 years of tweets harvested daily collected between 13 April 2020 and 10 January 2022 from the [Twitter API](https://developer.twitter.com/en/docs) using [TWARC](https://github.com/DocNow/twarc). Futher information on the corpus can be found in the [project\'s data repository](https://github.com/SAS-DHRH/covid-rumours-data)')


######################################
## Content
######################################

st.header('Summary')
st.markdown('Selected date range: **{} - {}**'.format(
    data_range_start.strftime('%d %B %Y'),
    data_range_end.strftime('%d %B %Y')
))

if data_range_start > data_range_end:
    st.error('Date range selection error: The end date must be later than the start date.')
    st.stop()


######################################
## Overview
######################################

col1, col2, col3 = st.columns(3)
col1.metric('Tweets', '{:,}'.format(selected_tweetdata.tweet_count.sum()), None)
col2.metric('Retweeted', '{:,}'.format(selected_retweetdata.retweet_count.sum()), None)
col3.metric('Favourited', '{:,}'.format(selected_retweetdata.favorite_count.sum()), None)

col4, col5, col6 = st.columns(3)
col4.metric('Replied', '{:,}'.format(selected_retweetdata.reply_count.sum()), None)
col5.metric('Quoted', '{:,}'.format(selected_retweetdata.quote_count.sum()), None)
col6.metric('New user accounts created', '{:,}'.format(selected_userdata.user_count.sum()), None)


######################################
## Tweets
######################################

st.header('Tweets')
tweets = alt.Chart(selected_tweetdata.reset_index()).mark_bar().encode(
    x = alt.X(
        'created_at:T', 
        title='Date', 
        scale={'domain':[selected_date_start, selected_date_end]},
        axis = alt.Axis(format='%Y-%m-%d')
    ),
    y = alt.Y(
        'tweet_count:Q', 
        title='Number of tweets'
    ),
    tooltip = [
        alt.Tooltip('created_at:T', title='Date'),
        alt.Tooltip('tweet_count:Q', title='Number of tweets', format=',.0f'),
    ]
).properties(
    title = "Tweets per day",
)
st.altair_chart(tweets.interactive(), use_container_width=True)


######################################
## Retweets
######################################

st.header('Retweeted tweets') 
st.write(selected_date_start)
st.write('The number of times the tweets have been retweeted.')
retweet_freq = alt.Chart(selected_retweetdata.reset_index()).mark_bar().encode(
    x = alt.X(
        'created_at:T', 
        title='Date', 
        scale={'domain':[selected_date_start, selected_date_end]},
        axis = alt.Axis(format='%Y-%m-%d')
    ),
    y = alt.Y(
        'retweet_count:Q', 
        title='Number of retweets'
    ),
    tooltip = [
        alt.Tooltip('created_at:T', title='Date'),
        alt.Tooltip('retweet_count:Q', title='Number of retweets', format=',.0f'),
    ]
).properties(
    title = "Retweeted tweets per day",
)
st.altair_chart(retweet_freq.interactive(), use_container_width=True)


######################################
## Favourites
######################################

st.header('Favourites')
st.write('The number of times the tweets have been favourited.')
favorite_freq = alt.Chart(selected_retweetdata.reset_index()).mark_bar().encode(
    x = alt.X(
        'created_at:T', 
        title='Date', 
        scale={'domain':[selected_date_start, selected_date_end]},
        axis = alt.Axis(format='%Y-%m-%d')
    ),
    y = alt.Y(
        'favorite_count:Q', 
        title='Number of favourites'
    ),
    tooltip = [
        alt.Tooltip('created_at:T', title='Date'),
        alt.Tooltip('favorite_count:Q', title='Number of favourites', format=',.0f'),
    ]
).properties(
    title = "Favourites per day",
)
st.altair_chart(favorite_freq.interactive(), use_container_width=True)


######################################
## Replies
######################################

st.header('Replies')
st.write('The number of times the tweets have been replied to.')
reply_freq = alt.Chart(selected_retweetdata.reset_index()).mark_bar().encode(
    x = alt.X(
        'created_at:T', 
        title='Date', 
        scale={'domain':[selected_date_start, selected_date_end]},
        axis = alt.Axis(format='%Y-%m-%d')
    ),
    y = alt.Y(
        'reply_count:Q', 
        title='Number of replies'
    ),
    tooltip = [
        alt.Tooltip('created_at:T', title='Date'),
        alt.Tooltip('reply_count:Q', title='Number of replies', format=',.0f'),
    ]
).properties(
    title = "Replies per day",
)
st.altair_chart(reply_freq.interactive(), use_container_width=True)


######################################
## Quotes
######################################

st.header('Quotes')
st.write('The number of times the tweets have been quoted.')
quote_freq = alt.Chart(selected_retweetdata.reset_index()).mark_bar().encode(
    x = alt.X(
        'created_at:T', 
        title='Date', 
        scale={'domain':[selected_date_start, selected_date_end]},
        axis = alt.Axis(format='%Y-%m-%d')
    ),
    y = alt.Y(
        'quote_count:Q', 
        title='Num of quotes'
    ),
    tooltip = [
        alt.Tooltip('created_at:T', title='Date'),
        alt.Tooltip('quote_count:Q', title='Number of quotes', format=',.0f'),
    ]
).properties(
    title = "Quotes per day",
)
st.altair_chart(quote_freq.interactive(), use_container_width=True)


######################################
## User account data
######################################

st.header('Account creation')
st.write('The number of new user accounts created.')
account_creation_freq = alt.Chart(selected_userdata.reset_index()).mark_bar().encode(
    x = alt.X(
        'created_at:T', 
        title='Date', 
        scale={'domain':[selected_date_start, selected_date_end]},
        axis = alt.Axis(format='%Y-%m-%d')
    ),
    y = alt.Y(
        'user_count:Q', 
        title='Number of accounts'
    ),
    tooltip = [
        alt.Tooltip('created_at:T', title='Date'),
        alt.Tooltip('user_count:Q', title='Number of accounts', format=',.0f'),
    ]
).properties(
    title = "Accounts created per day",
)
st.altair_chart(account_creation_freq.interactive(), use_container_width=True)
