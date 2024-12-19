document.getElementById("slideshow").style.display = "none";

// the timer that's running the slideshow. Gets started automatically by
// get_live_assets() if it's null
slideshow_timer = null;

// the list of live assets, as we got it from the api
content = {};

// the list of live asset ids, shuffled at the start of each run
content_shuffled = [];
currently_showing = 0;

function xhr_get(url, callback_func) {
    req = new XMLHttpRequest();
    req.timeout = 10000;
    req.open('GET', url);
    req.setRequestHeader('Accept', 'application/json');
    req.setRequestHeader("Content-Type", "application/json;charset=UTF-8");
    req.addEventListener('load', function(event) {
        if (req.status != 200) {
            return;
        }

        callback_func(event);
    });
    req.send();
}

// from https://stackoverflow.com/a/12646864
function shuffle_content() {
    console.debug("shuffling content");
    array = Object.keys(content);
    for (let i = array.length - 1; i >= 0; i--) {
        const j = Math.floor(Math.random() * (i + 1));
        [array[i], array[j]] = [array[j], array[i]];
    }
    content_shuffled = array;
}

// Auto-reload slideshow in case the backend has restarted. We need this
// to ensure we're running the latest code, without needing to press
// reload on every display individually.
window.setInterval(function() {
    console.info('checking if slideshow needs reloading because server has restarted');
    xhr_get('/api/startup', function() {
        startup = parseInt(req.responseText);
        if (startup > 0 && app_startup < startup) {
            console.warn('startup time has changed, reloading GUI');
            window.location.reload();
        } else {
            console.info('slideshow does not need reloading');
        }
    });
}, 42000);

// Load the list of live assets.
function get_live_assets() {
    console.info('loading live assets');
    xhr_get('/api/slideshow/content', function() {
        content = JSON.parse(req.responseText);
        console.info("got live assets, " + Object.keys(content).length + " assets in total");
        if (slideshow_timer === null && Object.keys(content).length > 0) {
            slideshow_tick();
            slideshow_timer = window.setInterval(slideshow_tick, 10000);
        }
    });
}

get_live_assets();
window.setInterval(get_live_assets, 300000);

// The actual magic starts here. This function knows about the current
// position in the slideshow and automatically selects the next available
// picture. If the current picture cannot be found in the list (aka it was
// deleted or expired) or we reach the end of the list, we start again
// from the beginning. In any case, we load the image into a temporary
// element, wait for it to finish loading, then replace the currently
// showing image. This ensures there's always an image showing.
function get_next_asset_to_show() {
    if (content_shuffled.length === 0) {
        shuffle_content();
    }

    // iterate over the shuffled content array to find the current asset,
    // then return the next one
    for (let i = 0; i < content_shuffled.length-1; i++) {
        if (currently_showing == content_shuffled[i]) {
            next_asset = content_shuffled[i + 1];
            currently_showing = next_asset;
            return content[next_asset];
        }
    }

    shuffle_content();
    next_asset = content_shuffled[0];
    currently_showing = next_asset;
    return content[next_asset];
}

function slideshow_tick() {
    document.getElementById("slideshow").style.display = "block";
    document.getElementById("error").style.display = "none";

    next_asset = get_next_asset_to_show();
    console.info("next asset is " + next_asset['url'] + " of type " + next_asset['type']);

    image = document.getElementById("slideshow-image");
    video = document.getElementById("slideshow-video");

    if (next_asset['type'] == 'image') {
        img = document.createElement("img");
        img.onload = function() {
            video.pause();
            video.currentTime = 0;
            video.style.display = "none";

            image.src = this.src;
            image.style.display = "block";
        }
        img.src = next_asset['url'];
    } else  if (next_asset['type'] == 'video') {
        image.style.display = "none";

        video.src = next_asset["url"];
        video.style.display = "block";
        video.play();
    } else {
        document.getElementById("slideshow").style.display = "none";
        document.getElementById("error").style.display = "block";
        document.getElementById("error-text").innerHTML = "unknown asset type " + next_asset["type"];

        console.warn("unknown asset type " + next_asset["type"] + " for asset " + next_asset["url"]);
    }
}
