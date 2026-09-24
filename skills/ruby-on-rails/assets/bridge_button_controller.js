// app/javascript/controllers/bridge/button_controller.js
// Usage: <%= link_to "Edit", edit_invoice_path(@invoice), data: { controller: "bridge--button", bridge_title: "Edit" } %>
// Hide the web element only when the running app build supports "button":
//   [data-bridge-components~="button"] [data-controller~="bridge--button"] { display: none; }
import { BridgeComponent } from "@hotwired/hotwire-native-bridge"

export default class extends BridgeComponent {
  static component = "button"

  connect() {
    super.connect()

    const title = this.bridgeElement.bridgeAttribute("title")
    this.send("connect", { title }, () => {
      this.element.click()
    })
  }
}
