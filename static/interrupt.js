'use strict'

const notyf = new Notyf({duration: 8000})

Vue.component('interrupt', {
  template: `
    <div>
      <template v-if='!selected_room'>
        <p v-for='room in rooms'>
          <button @click='selected_room=room.name' class='btn btn-lg btn-block'>
            {{room.name}}
          </button>
        </p>
      </template>
      <template v-else>
        <h2 class='text-centered'>{{selected_room}}</h2>
        <button @click='selected_room=null' class='btn btn-lg btn-block'>
          &lt; Back to room list..
        </button>
        <button @click='interrupt(room_info.device_id, i.data)' class='btn btn-primary btn-lg btn-block'
          v-for='i in room_info.interrupts'
        >
          Show '{{i.name}}'
        </button>
      </template>
    </div>
  `,
  data: () => ({
    selected_room: null,
    rooms: window.config.ROOMS,
    api_key: window.config.API_KEY,
  }),
  computed: {
    room_info() {
      for (const room of this.rooms) {
        if (room.name == this.selected_room)
          return room
      }
    },
  },
  methods: {
    interrupt(device_id, data) {
      Vue.http.post(`https://info-beamer.com/api/v1/device/${device_id}/node/root/remote/trigger`, {
        'api-key': this.api_key,
        'data': data,
      })
    },
  },
})

Vue.http.options.emulateJSON = true
Vue.http.interceptors.push(request => {
  return response => {
    if (response.status == 400) {
      notyf.error(response.data.error)
    } else if (response.status == 401) {
      notyf.error('Access denied. Try reloading the page')
    } else if (response.status == 403) {
      if (request.method != "GET") {
        notyf.error('Access denied')
      }
    }
  }
})

new Vue({el: "#main"})
