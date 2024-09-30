'use strict'

const notyf = new Notyf({duration: 8000})

const store = new Vuex.Store({
  strict: true,
  state: {
    assets: [],
    busy: 0,
  },
  mutations: {
    set_assets(state, {assets}) {
      state.assets = assets
    },
    modify_busy(state, delta) {
      state.busy += delta
    },
  },
  actions: {
    async update_content({commit}) {
      const r = await Vue.http.get('/content/list')
      commit('set_assets', {
        assets: r.data.assets
      })
    },
    async upload_asset({commit, dispatch}) {
      const input = document.createElement('input')
      input.type = 'file'
      input.accept = "image/jpeg,image/png,video/mp4"
      input.onchange = async e => {
        let file = e.target.files[0]
        const filetype = {
          'image/png': 'image',
          'image/jpeg': 'image',
          'video/mp4': 'video',
        }[file.type]
        if (!filetype) {
          notyf.error("Invalid file type")
          return
        }
        try {
          await dispatch('upload_asset_ib', {
            filetype: filetype,
            file: file,
          })
          notyf.success("Upload complete")
        } catch (e) {
          if (filetype == 'image') {
            notyf.error("Please make sure you're using JPEG and your image size is exactly 1920x1080.")
          } else {
            notyf.error("Your video must be H264 and must not be longer than 10 seconds")
          }
        }
      }
      input.click()
    },
    async upload_asset_ib({commit, dispatch}, {filetype, file}) {
      const r1 = (await Vue.http.post(`/content/upload`, {
        filetype: filetype,
      })).data
      let fd = new FormData()
      fd.append('file', file, r1.filename)
      fd.append('x-want-acl-trace', 'yes')
      fd.append('userdata', JSON.stringify({
        'user': r1.user,
      }))
      const api_key = r1.upload_key
      const r2 = (await Vue.http.post('https://info-beamer.com/api/v1/asset/upload', fd, {
        headers: {
          Authorization: 'Basic ' + btoa(':' + api_key),
        }
      })).data
      await dispatch('review_asset', {asset_id: r2.asset_id})
    },
    async review_asset({commit, dispatch}, {asset_id}) {
      await Vue.http.post(`/content/review/${asset_id}`)
      await dispatch("update_content")
    },
    async remove_asset({commit, dispatch}, {asset_id}) {
      await Vue.http.delete(`/content/${asset_id}`)
      await dispatch("update_content")
    },
    async update_asset({commit}, {asset_id, options}) {
      await Vue.http.post(`/content/${asset_id}`, options)
    },
  }
})

Vue.component('busy-icon', {
  // https://codepen.io/aurer/details/jEGbA
  template: `
    <svg version="1.1" xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" x="0px" y="0px" width="24px" height="30px" viewBox="0 0 24 30" style="enable-background:new 0 0 50 50;" xml:space="preserve">
      <rect x="0" y="9.87045" width="4" height="11.2591" :fill="color || '#333'">
        <animate attributeName="height" attributeType="XML" values="5;21;5" begin="0s" dur="0.6s" repeatCount="indefinite"></animate>
        <animate attributeName="y" attributeType="XML" values="13; 5; 13" begin="0s" dur="0.6s" repeatCount="indefinite"></animate>
      </rect>
      <rect x="10" y="5.87045" width="4" height="19.2591" :fill="color || '#333'">
        <animate attributeName="height" attributeType="XML" values="5;21;5" begin="0.15s" dur="0.6s" repeatCount="indefinite"></animate>
        <animate attributeName="y" attributeType="XML" values="13; 5; 13" begin="0.15s" dur="0.6s" repeatCount="indefinite"></animate>
      </rect>
      <rect x="20" y="8.12955" width="4" height="14.7409" :fill="color || '#333'">
        <animate attributeName="height" attributeType="XML" values="5;21;5" begin="0.3s" dur="0.6s" repeatCount="indefinite"></animate>
        <animate attributeName="y" attributeType="XML" values="13; 5; 13" begin="0.3s" dur="0.6s" repeatCount="indefinite"></animate>
      </rect>
    </svg>
  `,
  props: ['color'],
})

Vue.component('busy-indicator', {
  template: `
    <div class="busy-wrap" v-if='busy'>
      <div class='busy'>
        <busy-icon class='icon'/>
      </div>
    </div>
  `,
  computed: {
    busy() {
      return this.$store.state.busy > 0
    }
  }
})

Vue.component('asset-box', {
  template: `
    <div class='asset-box panel panel-default'>
      <div class='panel-heading'>
        Project
      </div>
      <div class='panel-body'>
        <img class='img-responsive' :src='asset.thumb + "?w=328&h=191&crop=none"'>
        <hr/>
        <div class='row'>
          <div class='col-xs-6'>
            <div class="form-group">
              <label class="control-label">First shown</label>
              <select class="form-control" v-model='starts'>
                <option :value='opt[0]' v-for='opt in start_values'>{{opt[1]}}</option>
              </select>
            </div>
          </div>
          <div class='col-xs-6'>
            <div class="form-group">
              <label class="control-label">Shown until</label>
              <select class="form-control" v-model='ends'>
                <option :value='opt[0]' v-for='opt in end_values'>{{opt[1]}}</option>
              </select>
            </div>
          </div>
        </div>
        <div class='row'>
          <div class='col-xs-6'>
            <button @click='review' class='btn btn-default' v-if='asset.state == "new"'>
              Request review
            </button>
            <div class='state-link review' v-if='asset.state == "review"'>
              In review (Video team will moderate shortly)
            </div>
            <a class='state-link confirmed' href='/' v-if='asset.state == "confirmed"'>
              Confirmed ✓
            </a>
            <a class='state-link rejected' href='/rejected' v-if='asset.state == "rejected"'>
              Rejected. <a href='/faq#rules'>Why?</a>
            </a>
          </div>
          <div class='col-xs-6 text-right'>
            <button @click='remove' class='btn btn-danger'>
              Delete
            </button>
          </div>
        </div>
      </div>
    </div>
  `,
  props: ['asset'],
  data() {
    return {
      starts: this.asset.starts,
      ends: this.asset.ends,
    }
  },
  computed: {
    start_values() {
      return this.make_timerange_option(null, this.ends, 'Now')
    },
    end_values() {
      return this.make_timerange_option(this.starts, null, 'Open end')
    },
  },
  watch: {
    async starts(new_ts, old_ts) {
      await this.$store.dispatch('update_asset', {
        asset_id: this.asset.id,
        options: {
          starts: new_ts,
          ends: this.ends,
        }
      })
      notyf.success("Start time saved")
    },
    async ends(new_ts, old_ts) {
      await this.$store.dispatch('update_asset', {
        asset_id: this.asset.id,
        options: {
          starts: this.starts,
          ends: new_ts,
        }
      })
      notyf.success("End time saved")
    },
  },
  methods: {
    make_timerange_option(min, max, unset) {
      let options = [[null, unset]]
      const config = window.config
      const now = Math.floor(Date.now() / 1000)
      // const start = Math.floor(Math.max(config.TIME_MIN, now, min || now) / 3600) * 3600
      // const end = Math.min(config.TIME_MAX, max || config.TIME_MAX)
      const start = Math.floor(config.TIME_MIN / 3600) * 3600
      const end = config.TIME_MAX
      const zfill = v => (v+'').length <= 1 ? '0' + v : v
      for (let ts = start; ts <= end; ts += 3600) {
        const date = new Date(ts * 1000)
        const text_string = zfill(date.getDate()) + '.' + zfill(date.getMonth()+1) + '. - ' +
                            zfill(date.getHours()) + ':00'
        options.push([ts, text_string])
      }
      return options
    },
    review() {
      this.$store.dispatch('review_asset', {
        asset_id: this.asset.id
      })
    },
    remove() {
      this.$store.dispatch('remove_asset', {
        asset_id: this.asset.id
      })
    },
  },
})

const Index = Vue.component('index', {
  template: `
    <div>
      <template v-if='assets.length > 0'>
        <div class='row'>
          <div class='col-md-4' v-for='asset in assets'>
            <asset-box :key='asset.id' :asset='asset'/>
          </div>
        </div>
      </template>
      <div class='alert alert-info' v-else>
        No projects yet.
      </div>
      <button @click='upload' class='btn btn-primary' :disabled='busy'>
        Upload FullHD JPG or 10s H264 video..
      </button>
      <br>
      The bottom 40 pixels of your content will be overlayed by a bar
      showing your github username and will therefore not be visible.
      Your project image/video <b>must</b> include a way to reach you
      during this event. If you're getting "Access denied" errors,
      double check that your file matches the specifications.
      <a href='/faq'>Read the FAQ..</a>
    </div>
  `,
  computed: {
    assets() {
      return this.$store.state.assets
    },
    busy() {
      return this.$store.state.busy > 0
    },
  },
  methods: {
    upload() {
      this.$store.dispatch('upload_asset')
    },
  },
})

const Dashboard = Vue.component('dashboard', {
  template: `
    <div>
      <router-view/>
    </div>
  `
})

Vue.component('VueCtkDateTimePicker', window['vue-ctk-date-time-picker']);

const router = new VueRouter({
  mode: 'history',
  base: '/dashboard',
  routes: [
    { path: '', component: Index },
  ],
  scrollBehavior(to, from, savedPosition) {
    if (savedPosition) {
      return savedPosition
    } else {
      return { x: 0, y: 0 }
    }
  }
})

Vue.http.options.emulateJSON = true
Vue.http.interceptors.push(request => {
  store.commit('modify_busy', +1)
  return response => {
    store.commit('modify_busy', -1)
    if (response.status == 400) {
      notyf.error(response.data.error)
    } else if (response.status == 401) {
      notyf.error('Access denied')
    } else if (response.status == 403) {
      if (request.method != "GET") {
        notyf.error('Access denied')
      }
    }
  }
})

store.dispatch('update_content')
new Vue({el: "#main", store, router, })
