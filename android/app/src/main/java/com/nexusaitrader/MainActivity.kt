package com.nexusaitrader

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Bolt
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Security
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

private val Bg = Color(0xFF080B16)
private val Panel = Color(0xFF12182A)
private val Cyan = Color(0xFF43D9FF)
private val Purple = Color(0xFF9B7CFF)
private val Muted = Color(0xFF98A4BD)
private const val BASE_URL = "http://10.0.2.2:8000"

data class AssetSnapshot(val symbol:String,val price:String,val signal:String,val detail:String)

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent { NexusDashboard() }
    }
}

private suspend fun requestJson(path:String, method:String="GET"): JSONObject = withContext(Dispatchers.IO) {
    val c = URL(BASE_URL + path).openConnection() as HttpURLConnection
    c.connectTimeout=8000; c.readTimeout=8000; c.requestMethod=method
    try {
        val stream = if (c.responseCode in 200..299) c.inputStream else c.errorStream
        val body = stream?.bufferedReader()?.use { it.readText() } ?: "{}"
        if (c.responseCode !in 200..299) throw IllegalStateException("API ${c.responseCode}: $body")
        JSONObject(body)
    } finally { c.disconnect() }
}

private suspend fun loadAsset(symbol:String):AssetSnapshot {
    val p=requestJson("/market/price/$symbol")
    val s=requestJson("/hybrid-analysis/$symbol?interval=1h")
    val price=p.optDouble("price",Double.NaN)
    return AssetSnapshot(symbol, if(price.isNaN()) "Unavailable" else "$"+"%,.4f".format(price),
        s.optString("signal","HOLD"), s.optString("reason",s.optString("regime","No explanation")))
}

@Composable
fun NexusDashboard() {
    var assets by remember { mutableStateOf<List<AssetSnapshot>>(emptyList()) }
    var cash by remember { mutableStateOf("--") }
    var equity by remember { mutableStateOf("--") }
    var botEnabled by remember { mutableStateOf(false) }
    var positions by remember { mutableStateOf(0) }
    var status by remember { mutableStateOf("Connect backend to begin.") }
    var busy by remember { mutableStateOf(false) }
    val scope= rememberCoroutineScope()

    suspend fun refresh() {
        busy=true
        try {
            assets=listOf("BTCUSDT","ETHUSDT","SOLUSDT").map { loadAsset(it) }
            val st=requestJson("/paper-bot/status")
            cash="%.2f".format(st.optDouble("cash_usdt",0.0))
            equity="%.2f".format(st.optDouble("equity_usdt",0.0))
            botEnabled=st.optBoolean("enabled",false)
            positions=st.optJSONArray("positions")?.length() ?: 0
            status="Connected • PAPER ONLY • Live orders disabled"
        } catch(e:Exception) {
            status="Connection issue: ${e.message?.take(110) ?: "backend unavailable"}"
        } finally { busy=false }
    }

    suspend fun botAction(path:String, message:String) {
        busy=true
        try { requestJson(path,"POST"); status=message; refresh() }
        catch(e:Exception) { status="Action failed: ${e.message?.take(100)}"; busy=false }
    }

    suspend fun runTick(symbol:String) {
        busy=true
        try {
            val result=requestJson("/paper-bot/tick/$symbol?interval=1h","POST")
            val actions=result.optJSONObject("execution")?.optJSONArray("actions")
            status=if(actions==null || actions.length()==0) "$symbol checked • no paper order" else "$symbol evaluated • ${actions.length()} paper action(s)"
            refresh()
        } catch(e:Exception) { status="Tick failed: ${e.message?.take(100)}"; busy=false }
    }

    LaunchedEffect(Unit) { refresh() }

    Surface(Modifier.fillMaxSize(),color=Bg) {
        LazyColumn(Modifier.fillMaxSize().padding(18.dp),verticalArrangement=Arrangement.spacedBy(14.dp)) {
            item {
                Row(verticalAlignment=Alignment.CenterVertically) {
                    Icon(Icons.Default.Bolt,null,tint=Cyan,modifier=Modifier.size(30.dp))
                    Spacer(Modifier.width(8.dp))
                    Column {
                        Text("NEXUS",color=Color.White,fontSize=23.sp,fontWeight=FontWeight.Black)
                        Text("AI TRADER  /  PAPER LAB",color=Muted,fontSize=10.sp,letterSpacing=2.sp)
                    }
                    Spacer(Modifier.weight(1f))
                    Surface(color=Color(0xFF12313A),shape=RoundedCornerShape(20.dp)) {
                        Text("● PAPER",color=Cyan,modifier=Modifier.padding(10.dp),fontSize=11.sp)
                    }
                }
            }
            item {
                Text("Trading command centre",color=Color.White,fontSize=24.sp,fontWeight=FontWeight.Bold)
                Text("Simulation only. No exchange orders are sent.",color=Purple,fontSize=12.sp)
            }
            item {
                CardPanel {
                    Row(verticalAlignment=Alignment.CenterVertically) {
                        Icon(Icons.Default.Security,null,tint=Purple)
                        Spacer(Modifier.width(8.dp))
                        Text("PAPER ACCOUNT",color=Muted,fontSize=11.sp,letterSpacing=1.sp)
                        Spacer(Modifier.weight(1f))
                        Text(if(botEnabled) "ENABLED" else "STOPPED",color=if(botEnabled) Cyan else Color(0xFFFFA0A0),fontWeight=FontWeight.Bold)
                    }
                    Spacer(Modifier.height(12.dp))
                    Row {
                        Metric("Cash", "\$$cash")
                        Spacer(Modifier.width(20.dp))
                        Metric("Equity", "\$$equity")
                        Spacer(Modifier.width(20.dp))
                        Metric("Positions", positions.toString())
                    }
                    Spacer(Modifier.height(10.dp))
                    Text("Risk limits: max 10% allocation • 2% daily loss shutdown • 2% stop / 4% target",
                        color=Muted,fontSize=11.sp)
                    Spacer(Modifier.height(10.dp))
                    Row(horizontalArrangement=Arrangement.spacedBy(8.dp)) {
                        Button(onClick={scope.launch { botAction("/paper-bot/start","Paper bot enabled.") }},enabled=!busy && !botEnabled,
                            colors=ButtonDefaults.buttonColors(containerColor=Cyan)) { Text("START PAPER",color=Bg) }
                        OutlinedButton(onClick={scope.launch { botAction("/paper-bot/stop","Paper bot stopped.") }},enabled=!busy && botEnabled) {
                            Text("STOP",color=Color.White)
                        }
                    }
                    Text("Start enables simulation only. It does not run continuously.",color=Muted,fontSize=10.sp)
                }
            }
            item {
                CardPanel {
                    Row(verticalAlignment=Alignment.CenterVertically) {
                        Text("SYSTEM STATUS",color=Muted,fontSize=11.sp,letterSpacing=1.sp)
                        Spacer(Modifier.weight(1f))
                        IconButton(onClick={if(!busy) scope.launch { refresh() }},enabled=!busy) {
                            Icon(Icons.Default.Refresh,null,tint=Cyan)
                        }
                    }
                    Text(status,color=Color.White,fontSize=12.sp)
                    if(busy) LinearProgressIndicator(Modifier.fillMaxWidth(),color=Cyan)
                }
            }
            item { Text("MARKET WATCH • HYBRID RULE ENGINE",color=Muted,fontSize=11.sp,letterSpacing=1.sp) }
            if(assets.isEmpty()) item { CardPanel { Text("No market data yet. Start the backend and refresh.",color=Muted) } }
            assets.forEach { a ->
                item {
                    CardPanel {
                        Row(verticalAlignment=Alignment.CenterVertically) {
                            Column(Modifier.weight(1f)) {
                                Text(a.symbol,color=Color.White,fontWeight=FontWeight.Bold,fontSize=17.sp)
                                Text(a.price,color=Cyan,fontSize=20.sp,fontWeight=FontWeight.Bold)
                            }
                            Text(a.signal,color=if(a.signal=="BUY") Cyan else if(a.signal=="SELL") Color(0xFFFF8EA1) else Muted,
                                fontWeight=FontWeight.Bold)
                        }
                        Spacer(Modifier.height(6.dp))
                        Text(a.detail,color=Muted,fontSize=11.sp)
                        Spacer(Modifier.height(8.dp))
                        OutlinedButton(onClick={scope.launch { runTick(a.symbol) }},enabled=!busy && botEnabled) {
                            Text("EVALUATE PAPER TICK",color=Cyan)
                        }
                    }
                }
            }
            item {
                CardPanel {
                    Text("SAFETY & EXECUTION",color=Muted,fontSize=11.sp,letterSpacing=1.sp)
                    Text("Live trading: DISABLED",color=Color.White,fontWeight=FontWeight.Bold)
                    Text("Futures / leverage: DISABLED",color=Color.White,fontWeight=FontWeight.Bold)
                    Text("Paper ticks are manual requests, not unattended automation. Historical performance does not predict returns.",
                        color=Muted,fontSize=11.sp)
                }
            }
            item {
                Text("NEXUS AI TRADER • Stage 10 • Development build",color=Muted,fontSize=10.sp,
                    modifier=Modifier.fillMaxWidth().wrapContentWidth(Alignment.CenterHorizontally))
            }
        }
    }
}

@Composable private fun Metric(label:String,value:String) {
    Column {
        Text(label,color=Muted,fontSize=10.sp)
        Text(value,color=Color.White,fontSize=17.sp,fontWeight=FontWeight.Bold)
    }
}
@Composable fun CardPanel(content:@Composable ColumnScope.()->Unit) {
    Surface(Modifier.fillMaxWidth(),color=Panel,shape=RoundedCornerShape(20.dp)) {
        Column(Modifier.padding(15.dp),content=content)
    }
}
