######################################
## COVID Rumours in Historical Context
## Dashboard: Tweets Explorer
######################################
#
# Constraints & issues
#
# 1. [Altair] Concatnated (vconcat, hconcat) charts do not work with Streamlit's use_container_width
#    and need to be configured with fixed width.
#    https://github.com/streamlit/streamlit/issues/700
#    https://github.com/streamlit/streamlit/issues/2751
#
# 2. [Altair] Tooltip font or box size cannot be changed. Long text can get chopped off.
#    https://github.com/altair-viz/altair/issues/1688
#    https://stackoverflow.com/questions/65798037/altair-tooltips-is-there-a-way-to-format-box-shape-for-long-text
#    https://github.com/altair-viz/altair/issues/1724
#
# 3. [Altair] No support for handling/repeling overlapping text marks (but it is in the works).
#    https://github.com/altair-viz/altair/issues/1731
#    https://github.com/vega/vega-lite/pull/7222
#    https://github.com/vega/vega-label
#
# 4. [Streamlit] st.dataframe widget has no column width property (but it is in the works). An alternative
#    is to use st.table() but it displays the entire dataset.
#    https://github.com/streamlit/streamlit/issues/371
#    https://discuss.streamlit.io/t/is-there-a-way-to-specify-column-width-for-dataframe-table/333
#
# 5. [Streamlit] st.selectbox widget does not support nested option (i.e. <optgroup>) yet.
#    e.g the taxonomy selector for constraining ngrams suggestions.
#    https://discuss.streamlit.io/t/nested-dropdown/16758/2

import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import altair as alt
import matplotlib.pyplot as plt
import networkx as nx
import yaml
import uuid
from time import perf_counter
from pyvis.network import Network

@st.cache(persist=True, ttl=60*60)
def load_dataframe(filepath, compression:str = 'infer'):
    '''
    Load csv into pandas dataframe.
    @filepath: Path to a csv file as string, or a set of paths as list or dictionary
    @compression: As per pandas API doc for read_csv (https://pandas.pydata.org/pandas-docs/stable/reference/api/pandas.read_csv.html)
    '''

    # @filepath is a string
    if isinstance(filepath, str):
        return pd.read_csv(filepath, compression=compression).reset_index(drop=True)

    # @filepath is a list
    if isinstance(filepath, list):
        dataframes =[pd.read_csv(file, compression=compression) for path in filepath]
        return pd.concat(dataframes)

    # @filepath is a dictionary
    if isinstance(filepath, dict):
        dataframes =[]
        keys = []
        for key in filepath:
            data = pd.read_csv(filepath[key], compression=compression)
            data['subset'] = key
            dataframes.append(data)
            keys.append(key)
        return pd.concat(dataframes, keys=keys, ignore_index=True).set_index('subset')

    return

@st.cache(persist=True, ttl=60*60)
def load_yaml(filename, parse=True):
    '''
    Load data from yaml files into a list of dictionaries.
    @filename: Path to a yaml file as string, or a set of paths as list or dictionary
    '''

    loaded = []

    for key, value in (filename.items() if isinstance(filename, dict) else enumerate(filename) if isinstance(filename, list) else []):
        with open(value) as file:
            loaded.append(yaml.load(file, Loader=yaml.SafeLoader))

    return loaded

@st.cache(persist=True, ttl=60*60)
def tidy_taxonomies(data:list):
    '''
    Clean up the taxonomies data loaded from yaml:
        - convert terms to lower case
        - split multiple words into single words

    Assumes the data is in the following structure:
    [
        {
            'category': 'name',
            'vocabulary': [
                'term',
                'another term'
            ],
            'subcategories': [
                {
                    'category': 'name',
                    'vocabulary': [
                        'term',
                        'another term'
                    ],
                    'subcategories': [
                        {...}
                    ]
                }
            ]
        },
        {
            'category': 'name',
            'vocabulary': [
                'term',
                'another term'
            ],
            'subcategories': [
                {...}
            ]
        }
    ]
    '''

    stopwords = [
        'and', '&',
        'or'
    ]

    processed = []

    for key, value in (data.items() if isinstance(data, dict) else enumerate(data) if isinstance(data, list) else []):
        taxonomy = {}
        if 'category' in value.keys():
            taxonomy['category'] = {
                'name': value['category'].lower(),
                'uuid': str(uuid.uuid4())
            }
        if 'vocabulary' in value.keys():
            taxonomy['vocabulary'] = []
            for string in value['vocabulary']:
                for word in string.split():
                    word = (word.lower()).replace('*', '')
                    if not word in stopwords:
                        taxonomy['vocabulary'].append({
                            'name': word,
                            'uuid': str(uuid.uuid4())
                        })
        if 'subcategories' in value.keys():
            taxonomy['subcategories'] = tidy_taxonomies(value['subcategories'])
        processed.append(taxonomy)

    return processed

@st.cache(persist=True, ttl=60*60)
def get_taxonomy_categories(data, path:list=[], level:int = 0):
    '''
    Returns a dictionary of taxonomy categories.
    @data: Taxonomies data loaded from yaml files.
    @path: Parent-child path of the node being processed, no need to supply when invoking the function, used only for generating the node's label.
    @level: Depth level of the node being processed, no need to supply when invoking the function, used only for keeping track of the node's hierachical position.

    Note: Taxonomy categories are assigned uuid, since same words can be used as category and term (e.g. the category 'Vaccines' and term 'vaccines') and those need to be differentiated.
    '''

    categories = {}

    for key, value in (data.items() if isinstance(data, dict) else enumerate(data) if isinstance(data, list) else []):
        if 'category' in value.keys():
            if level == 0:
                path.clear()
            elif len(path) > level:
                path = path[:len(path)-(len(path)-level)]
            path.append(value['category']['name'].capitalize())
            categories[value['category']['uuid']] = ' > '.join(path)
        if 'subcategories' in value.keys():
            result = get_taxonomy_categories(value['subcategories'], path, level + 1)
            if result:
                categories.update(result)

    return categories

@st.cache(persist=True, ttl=60*60)
def get_nx_taxonomies_graph(data, graph:nx.DiGraph = None, parent:str = None):
    '''
    Returns Networkx directed graph generated from taxonomies data.
    @data: Taxonomies data loaded from yaml files.
    @graph: Graph object, no need to supply when invoking the function, used only for injecting nested nodes and edges.
    @parent: Parent of the node being processed, no need to supply when invoking the function, used only for keeping track of the node's hierachical position.
    '''

    if graph == None:
        graph = nx.DiGraph()

    for key, value in (data.items() if isinstance(data, dict) else enumerate(data) if isinstance(data, list) else []):
        if 'category' in value.keys():
            category = value['category']['uuid']
            graph.add_node(category, label=value['category']['name'], type='category')
            if parent != None:
                graph.add_edge(parent, category)
        if 'vocabulary' in value.keys():
            for word in value['vocabulary']:
                graph.add_node(word['uuid'], label=word['name'], type='vocabulary')
                graph.add_edge(value['category']['uuid'], word['uuid'])
        if 'subcategories' in value.keys():
            get_nx_taxonomies_graph(value['subcategories'], graph, value['category']['uuid'])

    return graph

def get_taxonomy_vocabularies(graph:nx.Graph, category:str=None):
    '''
    Returns a list of taxonomy vocabularies, optionally filtered by a category.
    @graph: Taxonomies graph data generated with get_taxonomies_graph().
    @category: Category uuid to filter by.

    Note: Taxonomy terms are assigned uuid, since there can be same terms in different categories/context (e.g. the term 'vaccine' in Conspiracy and Vaccines categories).
    '''

    vocabularies = []

    if category == None:
        vocabularies = [y['label'] for x, y in graph.nodes(data=True) if y['type']=='vocabulary']
    elif graph.has_node(category):
        nodes = nx.descendants(graph, category)
        subgraph = graph.subgraph(nodes)
        vocabularies = [y['label'] for x, y in subgraph.nodes(data=True) if y['type']=='vocabulary']

    return sorted(vocabularies, key=str.casefold)

def get_nx_collocation_graph(bigrams:pd.DataFrame, words:list, type:str='pmi', top:int = 7):
    '''
    Returns Networkx graph generated from dataframe.
    @bigrams: bigrams dataframe to use.
    @words: List of words to collocate.
    @type: Type of collocation i.e. 'pmi' (Pointwise Mutual Information, default) or 'f_xy' (Bigram frequency).
    @top: Number of topmost collocates.

    NOTE: This only works in a forward direction
          i.e. words to collocate (source) -> topmost collocated words (target)
    '''

    # Drop unncessary data columns and rows
    df = bigrams.drop(['date'], axis=1).drop_duplicates()

    # Extract the rows where the 'x' (source) column value match any of
    # words to collocate (@words).
    x_collocates = df[df.x.isin(words)]

    # Extract the rows where the 'y' (target) column value match any of
    # the words to collocate (@words). For this subset, swap the 'x' and 'y'
    # columns, so we have all the words to collocate in the 'x' (source) column.
    y_collocates = df[df.y.isin(words)].rename(columns={"x": "y", "y": "x"})

    # Combine the extracted subsets into a new dataframe, and reorder the rows by 'x' (source) and @type columns.
    df_collocates = pd.concat([x_collocates, y_collocates]).sort_values(['x', type], ascending=False)

    # Group by 'x' (source) column and select the required topmost (@top) rows for each group.
    df_collocates = df_collocates.groupby('x').head(top)

    # Create graph strcutre from the dataframe.
    if df_collocates.empty:
        # No collocates were found but we still want to visualise this, so we'll create
        # a graph with the selected words as nodes.
        graph = nx.Graph()
        for word in words:
            graph.add_node(word)
    else:
        graph = nx.from_pandas_edgelist(df_collocates, 'x', 'y', edge_attr=[type])

    return graph

def get_matplotlib_network(graph: nx.classes.graph.Graph, options: dict = {}):
    '''
    Returns pyvis network object.
    @graph: Networkx graph.
    @config: pyvis network configuration.
    @options: pyvis network visualisation options.
    '''

    defaults = {
        "cmap": plt.cm.Reds,
        "width": 4,
        "font_size": 14,
        "edge_cmap": plt.cm.Blues,
        "with_labels": True,
    }
    options = {**defaults, **options}

    fig, ax = plt.subplots(figsize=(10,10))
    ax = nx.draw(graph, **options)

    return {'fig': fig, 'ax': ax}

def get_pyvis_network(graph:nx.Graph, config:dict = {}, options:str = ''):
    '''
    Returns pyvis network object.
    @graph: Networkx graph.
    @config: pyvis network object configuration.
    @options: pyvis network visualisation options.
    '''

    # Nework object config
    default_config = {
        'width': '500px',
        'height': '500px'
    }
    config = {**default_config, **config}

    # Pyvis graph options
    # For tweaking the visualisation, set the configure.enabled to true,
    # and optionally use configure.filter to show nodes, edges and/or
    # physics panels e.g.
    # "configure": {
    #   "enabled": true,
    #   "filter": "nodes, edges, layout, physics"
    # }
    default_options = '''var options = {
        "configure": {
            "enabled": false
        },
        "nodes": {
            "borderWidth": 0,
            "borderWidthSelected": 0,
            "color": {
                "border": "rgba(255,255,255,1)",
                "background": "rgba(97,170,197,1)",
                "highlight": {
                    "border": "rgba(255,255,255,1)",
                    "background": "rgba(47,120,147,1)"
                }
            },
            "font": {
                "face": "sans-serif"
            }
        },
        "edges": {
            "color": {
                "inherit": false,
                "color": "rgba(200,200,200,0.75)",
                "highlight": "rgba(140,140,140,0.75)"
            },
            "smooth": false
        },
        "physics": {
            "repulsion": {
                "centralGravity": 0.5,
                "springLength": 75,
                "springConstant": 0.0125
            },
            "minVelocity": 0.75,
            "solver": "repulsion"
        }
    }'''
    options = default_options if options == '' else options

    # Initiate PyVis network object
    network = Network(**config)

    # Take Networkx graph and translate it to a PyVis graph format
    network.from_nx(graph, default_node_size=15)

    # Apply pyvis network options
    network.set_options(options)

    return network

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
## Page and library setup
######################################

st.session_state["multipage"] = True
st.set_page_config(layout="wide")
load_css("assets/css/dashboard.css")


######################################
## Sidebar (dashboard settings)
######################################

with st.sidebar:

    st.title('Covid Rumours in Historical Context')

    data_load_state = st.text('Loading data... (may take 3 mins)')
    start = perf_counter()
    df_unigrams = load_dataframe({
        'all': 'data/ALL/unigrams.csv.gz',
        'conspiracy': 'data/CONSPIRACY/unigrams.csv.gz',
        'cures': 'data/CURES/unigrams.csv.gz',
        'origins': 'data/ORIGINS/unigrams.csv.gz',
        'vaccines': 'data/VACCINES/unigrams.csv.gz'
    })
    df_bigrams = load_dataframe({
        'all': 'data/ALL/bigrams.csv.gz',
        'conspiracy': 'data/CONSPIRACY/bigrams.csv.gz',
        'cures': 'data/CURES/bigrams.csv.gz',
        'origins': 'data/ORIGINS/bigrams.csv.gz',
        'vaccines': 'data/VACCINES/bigrams.csv.gz'
    })
    df_timeline = load_dataframe('data/timeline/covid-events.csv', compression='infer')
    dict_taxonomies = tidy_taxonomies(load_yaml({
        'conspiracy': 'data/taxonomies/conspiracy.yaml',
        'cures': 'data/taxonomies/cures.yaml',
        'origins': 'data/taxonomies/origins.yaml',
        'vaccines': 'data/taxonomies/vaccines.yaml'
    }))
    nx_taxonomies = get_nx_taxonomies_graph(dict_taxonomies)

    st.session_state.loadtime = perf_counter() - start
    data_load_state.text("Data cached! (took {:.2f}s to load)".format(st.session_state.loadtime))

    with st.form(key='dashboard_settings'):

        with st.expander("Tweets", expanded=True):

            corpus_subset_options = {
                'all': 'All',
                'conspiracy': 'Conspiracy',
                'cures': 'Cures',
                'origins': 'Origins',
                'vaccines': 'Vaccines'
            }
            corpus_subset = st.radio(
                label = 'Select all or a subset of tweets',
                options = list(corpus_subset_options.keys()),
                format_func = corpus_subset_options.get,
                index = 0
            )

        with st.expander("Date range", expanded=True):

            data_range_start = st.date_input(
                label = 'From (YYYY-MM-DD)',
                value = pd.to_datetime(min(df_unigrams['date']), format="%Y-%m-%d"),
                min_value = pd.to_datetime(min(df_unigrams['date']), format="%Y-%m-%d"),
                max_value = pd.to_datetime(max(df_unigrams['date']), format="%Y-%m-%d")
            )

            data_range_end = st.date_input(
                label = 'To (YYYY-MM-DD)',
                value = pd.to_datetime(max(df_unigrams['date']), format="%Y-%m-%d"),
                min_value = pd.to_datetime(min(df_unigrams['date']), format="%Y-%m-%d"),
                max_value = pd.to_datetime(max(df_unigrams['date']), format="%Y-%m-%d")
            )

        with st.expander("Word frequencies", expanded=False):

            ngramChart = st.checkbox(
                label = 'Show word frequencies',
                value = True
            )

            ngramPointChart = st.checkbox(
                label = 'Show as point chart',
                help = 'Replace the line chart with a smoothed point chart (LOESS smoothing)'
            )

            timelineChart = st.checkbox(
                label = 'Show timeline',
                help = 'Add timeline chart to the word frequencies chart'
            )

            # The following widget require an internal key manually assigned,
            # since Streamlit uses the label by default and there is another
            # widget with the same label within this app (i.e. collocData, collocHelp below)
            ngramData = st.checkbox(
                label = 'Show source data',
                help = 'Show the raw data used to generate the word frequencies chart',
                key = 'ngramData'
            )

            ngramHelp = st.checkbox(
                label = 'Show help',
                key = 'ngramHelp'
            )

        with st.expander("Word collocations", expanded=False):

            collocChart = st.checkbox(
                label = 'Show word collocations',
                help = 'Displays the word relations in graphical form'
            )

            collocation_type_options = {
                'f_xy': 'Frequency',
                'pmi': 'Pointwise Mutual Information (PMI)'
            }
            collocation_type = st.radio(
                label = 'Choose collocation type',
                options = list(collocation_type_options.keys()),
                format_func = collocation_type_options.get,
                index = 1,
                help = 'PMI is a meaningful probabiliy of co-occurrence, whereas frequency is just the number of times the words co-occur.'
            )

            # The following widgets require an internal key manually assigned,
            # since Streamlit uses the label by default and there is another
            # widget with the same label within this app (i.e. ngramData, ngramHelp above)
            collocData = st.checkbox(
                label = 'Show source data',
                help = 'Show the raw data used to generate the collocations network graphs',
                key = 'collocData'
            )

            collocHelp = st.checkbox(
                label = 'Show help',
                key = 'collocHelp'
            )

        st.form_submit_button('Update')


######################################
## Data
######################################

date_start = data_range_start.strftime('%Y-%m-%d')
date_end = data_range_end.strftime('%Y-%m-%d')

if data_range_start <= data_range_end:

    # Selected subsets
    unigrams = df_unigrams.loc[corpus_subset]
    bigrams = df_bigrams.loc[corpus_subset]
    unigrams = unigrams[(unigrams['date'] >= date_start) & (unigrams['date'] <= date_end)]
    bigrams = bigrams[(bigrams['date'] >= date_start) & (bigrams['date'] <= date_end)]
    timeline = df_timeline[(df_timeline['date'] >= date_start) & (df_timeline['date'] <= date_end)]

    # All and default word lists
    allwords = pd.DataFrame({'word':df_unigrams['word'].drop_duplicates()}).reset_index(drop=True)
    # defaultwords = ["contagion","undead","zombie","zombies"]
    defaultwords = ['truth', 'facts', 'lies', 'scam', 'hoax']

    # Taxonomy categories and vocabularies
    # Note: selection impacts on the range of options/suggestions
    # offered by the Explorer's word selector.
    taxonomy_categories = get_taxonomy_categories(dict_taxonomies)
    taxonomy_vocabularies = get_taxonomy_vocabularies(nx_taxonomies.copy())

    selected_words_options = get_taxonomy_vocabularies(nx_taxonomies, st.session_state.get('selected_taxonomy_category', []))
    if len(selected_words_options) > 0:
        # Convert the options list to dataframe as appending, removing, de-duping etc are a lot faster.
        selected_words_options = pd.DataFrame({'word':selected_words_options})
        # Append any existing selected words, even if those fall outside the selected taxonomy category, otherwise
        # Streamlit throws 'StreamlitAPIException: Every Multiselect default value must exist in options'.
        # An odd UI behaviour but possibly less jolting than existing selected words being automatically removed/disappearing.
        selected_words_options = pd.concat([selected_words_options, pd.DataFrame({'word':st.session_state.get('selected_words', [])})], ignore_index=True).drop_duplicates().reset_index(drop=True)
        explorer_option_expanded = True
    else:
        # Append taxonomy vocabularies to allwords, otherwise Streamlit throws 'StreamlitAPIException: Every Multiselect default value must exist in options'
        # when selected_taxonomy_category is set to 'None' i.e. unigrams do not necessarily contain taxonomy vocabularies.
        selected_words_options = pd.concat([allwords, pd.DataFrame({'word':taxonomy_vocabularies})], ignore_index=True).drop_duplicates().reset_index(drop=True)
        explorer_option_expanded = False


######################################
## Content
######################################

st.title('Dashboard: Tweets Explorer')
st.markdown('Selected tweets: **{}** <br /> Selected date range: **{} - {}**'.format(
    corpus_subset_options.get(corpus_subset),
    data_range_start.strftime('%d %B %Y'),
    data_range_end.strftime('%d %B %Y')
), unsafe_allow_html=True)

if data_range_start > data_range_end:
    st.error('Date range selection error: The end date must be later than the start date.')
    st.stop()

with st.form(key='ngrams_selector'):

    col1, col2 = st.columns((7,1))
    with col1:
        selected_words = st.multiselect(
            label = 'Words to explore',
            options = selected_words_options,
            default = st.session_state.get('selected_words', defaultwords),
            key = 'selected_words'
        )
    with col2:
        st.form_submit_button('Update')

with st.expander(label='Advanced options', expanded=explorer_option_expanded):

    selected_taxonomy_category_options = list(taxonomy_categories.keys())
    selected_taxonomy_category_options.insert(0,'None')
    if 'selected_taxonomy_category' in st.session_state:
        selected_taxonomy_category_index = selected_taxonomy_category_options.index(st.session_state.get('selected_taxonomy_category', 'None')) if st.session_state.get('selected_taxonomy_category', 'None') in selected_taxonomy_category_options else 0
    else:
        selected_taxonomy_category_index = 0
    selected_taxonomy_category = st.selectbox(
        label = 'Suggest words only from taxonomy category:',
        help = 'Limit word suggestions to those in a specific taxonomy category. Note: If you have any words selected already, those words will remain selected even if they do not fall into the specified taxonomy category.',
        options = selected_taxonomy_category_options,
        format_func = taxonomy_categories.get,
        index = selected_taxonomy_category_index,
        key = 'selected_taxonomy_category'
    )

# We use st.container() for each section, and prepare the default content here,
# and insert charts in placeholder st.container() later as we create them
# (see below DISPLAY CHARTS bits).

# Word frequencies section
ngram_container = st.container()
if ngramChart:

    with ngram_container:

        if timelineChart:
            st.header('Word frequencies and timeline')
        else:
            st.header('Word frequencies')

        # ngram charts are added here
        ngram_chart_container = st.container()

        if ngramHelp:

            with st.expander('Help', True):
                st.markdown("""
                    Word frequencies chart:
                    - View details by hovering over any part of a line or point.
                    - Highlight a line or points by clicking on a legend/key label. Select multiple legend/key labels by clicking on each while holding down the shift key. To reset, click anywhere in the chart.
                    - Zoom in or out by hovering your mouse pointer over the chart and scrolling up or down. Zooming is centered on the position of your mouse pointer.
                    - Move the entire chart by dragging anywhere in the chart area.
                """)
                st.markdown("<br />", unsafe_allow_html=True)
                st.markdown("""
                    Timeline:
                    - View details by hovering over an event mark or label in the timeline.
                    - Drag your mouse pointer across the timeline to select a timespan (indicated by grey box), and the word frequencies chart will zoom into the selected timespan. Drag the selection to move the word frequencies chart back and forth along the date axis. To reset, click anywhere outside the selection in the timeline.
                """)
                st.markdown('<br />', unsafe_allow_html=True)

# Word collocations section
colloc_container = st.container()
if collocChart:

    with colloc_container:

        st.header('Word collocations by {}'.format(collocation_type_options.get(collocation_type)))

        col1, col2, col3 = st.columns((3, 1, 1))
        with col1:
            selected_collocation_words_options = (selected_words_options[~selected_words_options.word.isin(st.session_state.get('selected_words', []))])
            # Append any existing selected words, even if those fall outside the selected taxonomy category, otherwise
            # Streamlit throws 'StreamlitAPIException: Every Multiselect default value must exist in options'.
            # An odd UI behaviour but possibly less jolting than existing selected words being automatically removed/disappearing.
            selected_collocation_words_options = pd.concat([selected_collocation_words_options, pd.DataFrame({'word': st.session_state.get('selected_collocation_words', [])})], ignore_index=True).drop_duplicates().reset_index(drop=True)
            selected_collocation_words = st.multiselect(
                label = 'Additional words to collocate',
                options = selected_collocation_words_options,
                default = st.session_state.get('selected_collocation_words', []),
                key = 'selected_collocation_words'
            )
        with col2:
            number_of_collocates = st.number_input(
                label = 'Number of collocates',
                min_value = 1,
                max_value = 10,
                value = 7,
                step = 1
            )
        with col3:
            cf_corpus_subset_options = list(corpus_subset_options.keys())
            # Filter out already selected corpus subset
            # cf_corpus_subset_options.remove(corpus_subset)
            cf_corpus_subset_options.insert(0,'None')
            try:
                cf_corpus_subset_index = cf_corpus_subset_options.index(st.session_state.get('cf_corpus_subset', 'None')) if st.session_state.get('cf_corpus_subset', 'None') in cf_corpus_subset_options else 0
            except:
                cf_corpus_subset_index = 0
            cf_corpus_subset = st.selectbox(
                label = 'Compare to',
                options = cf_corpus_subset_options,
                format_func = corpus_subset_options.get,
                index = cf_corpus_subset_index,
                key = 'cf_corpus_subset'
            )

        # word collocation charts are added here
        colloc_chart_container = st.container()

        if collocHelp:

            with st.expander('Help', True):
                st.markdown("""
                    Word collocations graph:
                    - The selected words are in a different colour to the collocated words, and the thickness of the connecting lines reflect the scale of co-occurrence.
                    - Click on a word (node) to highlight its connections (edges) to collocates. To reset, click any empty space within the graph area (indicated by bordered box).
                    - Zoom in or out by hovering your mouse pointer over the graph and scrolling up or down. Zooming is centered on the position of your mouse pointer.
                    - Move a cluster by dragging a node attached to the cluster.
                    - Move the entire chart by dragging any empty space in the graph.
                """)
                st.markdown('<br />', unsafe_allow_html=True)
                st.markdown("""
                    Please note:
                    - Clusters will graviate towards each other, and this is only to prevent them from getting lost out of the graph area and has no statistical meaning or relevance.
                    - When there are two graphs displayed for comparison, node sizes may differ between the two initially when loaded, but this is because the graphs are generated to fit the graph area and this has no statistical meaning or relevance.
                """)
                st.markdown('<br />', unsafe_allow_html=True)


######################################
## Charts
######################################

# Set static chart width for concatnated chart (see issue #1 above)
chart_width = 1200

if ngramChart:

    # One or more ngrams are selected, create charts
    if len(selected_words) != 0:

        # ---------------
        # SETTINGS
        # ---------------

        # Set the mark opacity to 0.5 (half transparent) if ngram point chart is selected;
        # otherwise set it to 1 (not transparent)
        ngram_mark_opacity = 0.5 if ngramPointChart else 1

        # Set the x axis scale domain to 'brush' if paired with timeline chart; otherwise
        # set it to the selected date range.
        ngram_xscale_domain = alt.selection_interval(encodings = ['x']) if timelineChart else [date_start, date_end]
        # set the x axis scale domain to selected date range.
        timeline_xscale_domain = [date_start, date_end]

        # Capture ngram legend selection i.e. user clicks one or more legend item
        ngram_legend_selection = alt.selection_multi(fields=['word'], bind='legend')

        # ---------------
        # DATA
        # ---------------

        selected_unigrams = unigrams[unigrams['word'].isin(selected_words)].reset_index()
        selected_timeline = timeline

        # ---------------
        # CREATE CHARTS
        # ---------------

        # Line chart (default)
        if not ngramPointChart:

            ngram_line = alt.Chart(selected_unigrams).mark_line(size=2).encode(
                x = alt.X(
                    'date:T',
                    scale = alt.Scale(domain=ngram_xscale_domain),
                    title = 'date',
                    axis = alt.Axis(format='%Y-%m-%d')
                ),
                y = alt.Y('frequency:Q'),
                color = alt.Color('word:N', legend=alt.Legend(orient='top', title='Selected words:')),
                opacity=alt.condition(ngram_legend_selection, alt.value(1), alt.value(0.25)),
                tooltip = ['word:N', 'date:T', 'frequency:Q']
            )

            ngram_circle = ngram_line.mark_circle(size=60).encode(
                opacity = alt.value(0)
            )

            ngram_chart = alt.layer(
                ngram_line,
                ngram_circle
            ).add_selection(
                ngram_legend_selection
            )

        # Point chart
        if ngramPointChart:

            ngram_circle = alt.Chart(selected_unigrams).mark_circle().encode(
                x = alt.X(
                    'date:T',
                    scale = alt.Scale(domain=ngram_xscale_domain),
                    title = 'date',
                    axis = alt.Axis(format='%Y-%m-%d')
                ),
                y = alt.Y(
                    'frequency:Q',
                    impute=alt.ImputeParams(value=0)
                ),
                color = alt.Color('word:N', legend=alt.Legend(orient='top', title='Selected words:')),
                opacity = alt.condition(ngram_legend_selection, alt.value(ngram_mark_opacity), alt.value(0.15)),
                tooltip = ['word:N', 'date:T', 'frequency:Q']
            )

            ngram_chart = alt.layer(
                ngram_circle
            ).add_selection(
                ngram_legend_selection
            )

        # Timeline chart
        if timelineChart:

            timeline_point = alt.Chart(selected_timeline).mark_point(
                size = 6,
                color = '#E75480'
            ).encode(
                alt.X(
                    'date:T',
                    scale = alt.Scale(domain=timeline_xscale_domain),
                    title = 'date',
                    axis = alt.Axis(format='%Y-%m-%d', gridColor='#eee')
                ),
                alt.Y(
                    'position:Q',
                    axis = alt.Axis(domainOpacity=0, labelOpacity=0, tickOpacity=0, title=None, grid=False)
                ),
                tooltip = ['date:T', 'description:N']
            ).properties(
                width = chart_width,
                height=400
            )

            timeline_text = timeline_point.mark_text(
                # if text marks need adjusting, change fontSize, limit, dx and dy values here.
                align = 'center',
                baseline = 'bottom',
                fontSize = 10,
                lineBreak = '\n',
                limit = 80,
                dx = 6,
                dy = -16
            ).encode(
                y = 'position:Q',
                text = 'summary:N'
            ).add_selection(
                ngram_xscale_domain
            )

            timeline_chart = alt.layer(
                timeline_point,
                timeline_text
            )

        # Bar chart (default)
        else:

            ngram_bar = alt.Chart(selected_unigrams).mark_bar(opacity=ngram_mark_opacity).encode(
                y = "sum(frequency)",
                x = alt.X("word",sort="-y"),
                color = alt.Color('word:N', legend=None),
                opacity=alt.condition(ngram_legend_selection, alt.value(1), alt.value(0.25)),
                tooltip = ['word:N', "sum(frequency)"]
            ).add_selection(
                ngram_legend_selection
            )

    # ---------------
    # DISPLAY CHARTS
    # ---------------

    with ngram_chart_container:

        if len(selected_words) != 0:

            # Ngram line/point chart and timeline chart
            if timelineChart:

                compound_chart = alt.vconcat(
                    ngram_chart.properties(width=chart_width),
                    timeline_chart
                )

                st.altair_chart(compound_chart, use_container_width=True)

            # Ngram line/point chart and bar chart
            else:

                compound_chart = alt.hconcat(
                    ngram_chart.properties(width=chart_width - 200),
                    ngram_bar
                ).configure_legend(
                    titleFontSize = 14,
                    titleFontWeight = 500,
                    labelFontSize = 14
                )

                st.altair_chart(compound_chart, use_container_width=True)

            # Source data
            if ngramData:

                if timelineChart:

                    # Remove irrelevant columns from the timeline data i.e. 'summary'
                    # and 'position' columns, which are helper data for timeline chart creation.
                    selected_timeline_sanitised = selected_timeline.drop(['summary', 'position'], axis=1)

                    with st.expander('Word frequencies and timeline source data'):
                        col1, col2 = st.columns((1,1))
                        with col1:
                            st.markdown('<p style="margin-bottom: 0;">Word frequencies:</p>', unsafe_allow_html=True)
                            st.dataframe(selected_unigrams)
                        with col2:
                            st.markdown('<p style="margin-bottom: 0;">Timeline:</p>', unsafe_allow_html=True)
                            st.dataframe(selected_timeline_sanitised)

                else:
                    with st.expander('Word frequencies source data'):
                        st.dataframe(selected_unigrams)

        else:

            st.info('No word selected. Please enter one or more words above.')


if collocChart:

    ######################################
    # experimenting with colocation graphs
    # @src https://github.com/kennethleungty/Pyvis-Network-Graph-Streamlit
    #
    # Uses Pointwise Mutual Information scores (PMI)
    # @src https://stackoverflow.com/a/35852752
    #

    # One or more ngrams are selected, create charts
    if len(selected_words) != 0:

        # ---------------
        # SETTINGS
        # ---------------

        # Generate visualisation with 'pyvis' (default) or 'matplotlib'.
        visualisation_library = 'pyvis'

        # ---------------
        # DATA
        # ---------------

        words_to_collocate = list(set(selected_words + selected_collocation_words))

        # Default graph
        collocations = get_nx_collocation_graph(
            bigrams,
            words_to_collocate,
            collocation_type,
            number_of_collocates
        )
        # debug
        # st.write(collocations.nodes(data=True))
        # st.write(collocations.edges(data=True))

        # Comparison graph
        if cf_corpus_subset != 'None':

            cf_bigrams = df_bigrams.loc[cf_corpus_subset]
            cf_bigrams = cf_bigrams[(cf_bigrams['date'] >= date_start) & (cf_bigrams['date'] <= date_end)]

            cf_collocations = get_nx_collocation_graph(
                cf_bigrams,
                words_to_collocate,
                collocation_type,
                number_of_collocates
            )
            # debug
            # st.write(cf_collocations.nodes(data=True))
            # st.write(cf_collocations.edges(data=True))

        # ---------------
        # CREATE CHARTS
        # ---------------

        # Matplotlib visualisation
        if visualisation_library == 'matplotlib':

            collocational_network = get_matplotlib_network(
                collocations,
                {
                    "node_color": [int(n in words_to_collocate) for n in collocations.nodes],
                    "edge_color": [collocations[u][v][collocation_type] for u,v in collocations.edges],
                    "pos": nx.spring_layout(collocations, weight=collocation_type, seed=3, k=0.35, iterations=20),
                }
            )

            if cf_corpus_subset != 'None':

                cf_collocational_network = get_matplotlib_network(
                    cf_collocations,
                    {
                        "node_color": [int(n in words_to_collocate) for n in cf_collocations.nodes],
                        "edge_color": [cf_collocations[u][v][collocation_type] for u,v in cf_collocations.edges],
                        "pos": nx.spring_layout(cf_collocations, weight=collocation_type, seed=3, k=0.35, iterations=20),
                    }
                )

        # Pyvis visualisation
        else:

            # Set width and height of the pyvis network container (div#mynetwork)
            # in the generated html file. Adjust the height depending on whether
            # another (comapre to) corpus subset is selected.
            pyvis_config = dict(
                width = '100%',
                height = '800px'
            )

            # Set the location to save the pyvis generated html file
            pyvis_save_path = 'assets/pyvis_html'

            # Set the height of the iframe created by Streamlit's components.html(),
            # because it defaults to 300px. The html generated by pyvis has margins,
            # paddings and borders, and those need to be taken into account and the
            # iframe height set accordingly. Page, container, or column width is used
            # for the iframe width.
            st_iframe_height = int(pyvis_config['height'].replace('px', '')) + 24

            # Node attributes to override the defaults set in get_pyvis_network()
            node_attributes = {
                'color': 'rgba(214,67,137,1)',
                'size': 14
            }

            # Set colour and size of the selected words/nodes to visually
            # distinguish them from collocated words/nodes.
            attributes = {}
            for n in collocations.nodes():
                if n in words_to_collocate:
                    attributes[n] = node_attributes
            nx.set_node_attributes(collocations, attributes)

            # Vis.js expects the edge weight to be given as 'value' (not 'weight') attribute,
            # so duplicate the @group attribute ('pmi' or 'f_xy') and name it 'value'.
            # https://github.com/WestHealth/pyvis/issues/82
            attributes = {}
            for n in collocations.edges():
                attributes[n] = {
                    'value': collocations.edges[n][collocation_type]
                }
            nx.set_edge_attributes(collocations, attributes)

            collocational_network = get_pyvis_network(
                collocations,
                pyvis_config
            )
            # Set Jinja template
            # collocational_network.set_template(f'{pyvis_save_path}/pyvis_template.html')
            # Save and read graph as HTML file
            collocational_network.save_graph(f'{pyvis_save_path}/collocations.html')
            collocational_network_html = open(f'{pyvis_save_path}/collocations.html', 'r', encoding='utf-8')

            if cf_corpus_subset != 'None':

                # Set colour and size of the selected words/nodes to visually
                # distinguish them from collocated words/nodes.
                attributes = {}
                for n in cf_collocations.nodes():
                    if n in words_to_collocate:
                        attributes[n] = node_attributes
                nx.set_node_attributes(cf_collocations, attributes)

                # Vis.js expects the edge weight to be given as 'value' (not 'weight') attribute,
                # so duplicate the @group attribute ('pmi' or 'f_xy') and name it 'value'.
                # https://github.com/WestHealth/pyvis/issues/82
                attributes = {}
                for n in cf_collocations.edges():
                    attributes[n] = {
                        'value': cf_collocations.edges[n][collocation_type]
                    }
                nx.set_edge_attributes(cf_collocations, attributes)

                cf_collocational_network = get_pyvis_network(
                    cf_collocations,
                    pyvis_config
                )
                # Set Jinja template
                # cf_collocational_network.set_template(f'{pyvis_save_path}/pyvis_template.html')
                # Save and read graph as HTML file
                cf_collocational_network.save_graph(f'{pyvis_save_path}/collocations_cf.html')
                cf_collocational_network_html = open(f'{pyvis_save_path}/collocations_cf.html', 'r', encoding='utf-8')

    # ---------------
    # DISPLAY CHARTS
    # ---------------

    with colloc_chart_container:

        if len(selected_words) != 0:

            if cf_corpus_subset == 'None':

                st.markdown('Collocations in **{}**'.format(corpus_subset_options.get(corpus_subset)))

                if visualisation_library == 'matplotlib':

                    st.pyplot(collocational_network['fig'], clear_figure=None)

                else:

                    components.html(collocational_network_html.read(), height=st_iframe_height)

            else:

                col1, col2 = st.columns((1,1))
                with col1:

                    st.markdown('Collocations in **{}**'.format(corpus_subset_options.get(corpus_subset)))

                    if visualisation_library == 'matplotlib':
                        st.pyplot(collocational_network['fig'], clear_figure=None)

                    else:
                        components.html(collocational_network_html.read(), height=st_iframe_height)

                with col2:

                    st.markdown('Collocations in **{}**'.format(corpus_subset_options.get(cf_corpus_subset)))

                    if visualisation_library == 'matplotlib':

                        st.pyplot(cf_collocational_network['fig'], clear_figure=None)

                    else:

                        components.html(cf_collocational_network_html.read(), height=st_iframe_height)

            # Source data
            if collocData:

                # Convert the Networkx data back to pandas dataframe and select columns to show.
                source_data = nx.to_pandas_edgelist(collocations)[['source', 'target', collocation_type]]
                if cf_corpus_subset != 'None':
                    cf_source_data = nx.to_pandas_edgelist(cf_collocations)[['source', 'target', collocation_type]]

                if cf_corpus_subset == 'None':

                    with st.expander('Word collocations source data'):
                        st.dataframe(source_data)

                else:

                    with st.expander('Word collocations source data'):
                        col1, col2 = st.columns((1,1))
                        with col1:
                            st.markdown('<p style="margin-bottom: 0;">{}:</p>'.format(corpus_subset_options.get(corpus_subset)), unsafe_allow_html=True)
                            st.dataframe(source_data)
                        with col2:
                            st.markdown('<p style="margin-bottom: 0;">{}:</p>'.format(corpus_subset_options.get(cf_corpus_subset)), unsafe_allow_html=True)
                            st.dataframe(cf_source_data)

        else:

            st.info('No words to collocate. Please select one or more words.')
