'use strict'

Vue.component('moderate', {
  template: `
    <div>
      <h2>
        Upload by {{asset.username}}
      </h2>
      <div class='embed-responsive embed-responsive-16by9' v-if='asset.filetype == "video"'>
        <video class="embed-responsive-item" width="1920" height="1080" controls autoplay loop muted>
          <source :src='asset.url' type='video/mp4'/>
        </video>
      </div>
      <img class='img-responsive' :src='asset.url' v-else/>
      <hr/>
      <template v-if='needs_moderation'>
        <p class='text-centered'>
          Current state: <strong>{{asset.state}}</strong><br>
          Moderated by: <strong>{{asset.moderated_by}}</strong><br>
          Start time: <strong>{{epoch2String(asset.starts)}}</strong><br>
          End time: <strong>{{epoch2String(asset.ends)}}</strong>
        </p>
        <div class='row'>
          <div class='col-xs-6'>
            <button @click='moderate("confirm")' class='btn btn-lg btn-block btn-success'>
              Confirm
            </button>
          </div>
          <div class='col-xs-6'>
            <button @click='moderate("reject")' class='btn btn-lg btn-block btn-danger'>
              Reject
            </button>
          </div>
        </div>
      </template>
      <div class='alert alert-success text-centered' v-if='completed'>
        Thanks for moderating.
      </div>
    </div>
  `,
  data: () => ({
    needs_moderation: true,
    completed: false,
  }),
  props: ['asset'],
  methods: {
    async moderate(result) {
      this.needs_moderation = false
      await Vue.nextTick()
      await Vue.http.post(`/content/moderate/${this.asset.id}/${result}`)
      this.completed = true
    },
    epoch2String(epoch) {
      if (!epoch) return "None set";
      let date = new Date(0);
      date.setUTCSeconds(epoch);
      return date.toLocaleString();
    }
  },
})

new Vue({el: "#main"})
